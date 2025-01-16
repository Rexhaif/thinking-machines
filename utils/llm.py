from typing import Optional, Dict, Any, NamedTuple
import json
import re
from openai import OpenAI
from pathlib import Path
from .ui import thinking_spinner
import time
from json_repair import repair_json

class TokenUsage(NamedTuple):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int
    prompt_time: float
    completion_time: float

class LLMClient:
    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        top_p: float = 1.0,
        debug_dir: Optional[Path] = None,
        enforce_json_response: bool = True
    ):
        self.model = model
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.debug_dir = debug_dir
        self.call_counter = 0
        self.enforce_json_response = enforce_json_response
        
        # Load system prompt
        prompt_path = Path(__file__).parent.parent / "res" / "system.prompt.md"
        with open(prompt_path) as f:
            self.system_prompt = f.read()
            
    def _extract_json_from_markdown(self, text: str) -> str:
        """Extract JSON content from markdown-formatted text."""
        # Try to find JSON content between markdown code blocks
        json_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
        matches = re.findall(json_pattern, text)
        
        if matches:
            # Return the first JSON-like content found
            return matches[0].strip()
        
        # If no markdown blocks found, return the original text
        return text.strip()
    
    def _parse_response_content(self, content: str) -> Dict[str, Any]:
        """Parse response content, handling various formats."""
        try:
            # First try direct JSON parsing
            return json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown
            extracted_content = self._extract_json_from_markdown(content)
            try:
                return json.loads(extracted_content)
            except json.JSONDecodeError:
                # As a last resort, try to repair the JSON
                try:
                    repaired_json = repair_json(extracted_content)
                    return json.loads(repaired_json)
                except Exception as e:
                    raise ValueError(f"Failed to parse response as JSON even after repair attempt: {e}")
    
    def _save_debug_info(self, messages: list[Dict[str, str]], response: Any, **kwargs):
        """Save debug information about the API call."""
        if not self.debug_dir:
            return
            
        self.call_counter += 1
        
        # Extract all available usage attributes
        usage_data = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }
        
        # Add OpenAI-specific details if present
        if hasattr(response.usage, "prompt_tokens_details"):
            usage_data["prompt_tokens_details"] = response.usage.prompt_tokens_details
        if hasattr(response.usage, "completion_tokens_details"):
            usage_data["completion_tokens_details"] = response.usage.completion_tokens_details
            
        # Add Deepseek-specific details if present
        if hasattr(response.usage, "prompt_cache_hit_tokens"):
            usage_data["prompt_cache_hit_tokens"] = response.usage.prompt_cache_hit_tokens
        if hasattr(response.usage, "prompt_cache_miss_tokens"):
            usage_data["prompt_cache_miss_tokens"] = response.usage.prompt_cache_miss_tokens
        
        debug_data = {
            "call_number": self.call_counter,
            "timestamp": time.time(),
            "request": {
                "messages": [
                    {
                        "role": msg["role"],
                        "content": msg["content"]
                    } for msg in messages
                ],
                "model": self.model,
                "temperature": kwargs.get("temperature", self.temperature),
                "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                "top_p": kwargs.get("top_p", self.top_p),
                "enforce_json_response": self.enforce_json_response
            },
            "response": {
                "content": response.choices[0].message.content,
                "usage": usage_data
            }
        }
        
        debug_file = self.debug_dir / f"call_{self.call_counter:03d}.json"
        with open(debug_file, "w", encoding="utf-8") as f:
            json.dump(debug_data, f, indent=2, ensure_ascii=False, default=str)
    
    def format_task_message(
        self,
        task: str,
        mode: str = "EXPLORE_OPTIMAL",
        language: str = "English",
        max_steps: int = 10
    ) -> str:
        """Format the task message according to the prompt specification."""
        message = f"TASK: ```{task}```\n"
        if mode != "EXPLORE_OPTIMAL":
            message += f"MODE: {mode}\n"
        if language != "English":
            message += f"REASONING_LANGUAGE: {language}\n"
        if max_steps != 10:
            message += f"MAX_STEPS: {max_steps}\n"
        return message
    
    def _extract_token_usage(self, usage: Any, total_time: float) -> TokenUsage:
        """Extract token usage from response, supporting both OpenAI and Deepseek formats."""
        total_tokens = usage.total_tokens
        prompt_tokens = usage.prompt_tokens
        completion_tokens = usage.completion_tokens
        
        # Calculate timing
        prompt_ratio = prompt_tokens / total_tokens if total_tokens > 0 else 0.5
        prompt_time = total_time * prompt_ratio
        completion_time = total_time * (1 - prompt_ratio)
        
        # Handle cached tokens based on available information
        cached_tokens = 0
        
        # Try OpenAI format first
        prompt_details = getattr(usage, 'prompt_tokens_details', None)
        if prompt_details is not None:
            cached_tokens = getattr(prompt_details, 'cached_tokens', 0)
        
        # Try Deepseek format
        elif hasattr(usage, 'prompt_cache_hit_tokens'):
            cached_tokens = getattr(usage, 'prompt_cache_hit_tokens', 0)
        
        return TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cached_tokens=cached_tokens,
            prompt_time=prompt_time,
            completion_time=completion_time
        )

    def get_completion(
        self,
        messages: list[Dict[str, str]],
        **kwargs
    ) -> tuple[Dict[str, Any], TokenUsage, Any]:
        """Get completion from the OpenAI API and parse the JSON response."""
        with thinking_spinner():
            start_time = time.time()
            full_messages = [{"role": "system", "content": self.system_prompt}, *messages]
            
            # Prepare request parameters
            request_params = {
                "model": self.model,
                "messages": full_messages,
                "temperature": kwargs.get("temperature", self.temperature),
                "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                "top_p": kwargs.get("top_p", self.top_p),
            }
            
            # Add response format only if enforcing JSON
            if self.enforce_json_response:
                request_params["response_format"] = {"type": "json_object"}
            
            response = self.client.chat.completions.create(**request_params)
            
            # Save debug information if enabled
            if self.debug_dir:
                self._save_debug_info(full_messages, response, **kwargs)
            
            end_time = time.time()
            total_time = end_time - start_time
            
            # Extract token usage using the new helper method
            token_usage = self._extract_token_usage(response.usage, total_time)
            
            try:
                parsed_response = self._parse_response_content(response.choices[0].message.content)
                return parsed_response, token_usage, response
            except ValueError as e:
                raise ValueError(f"Failed to parse response: {e}")
    
    def start_reasoning(
        self,
        task: str,
        mode: str = "EXPLORE_OPTIMAL",
        language: str = "English",
        max_steps: int = 10
    ) -> tuple[Dict[str, Any], list[Dict[str, str]], TokenUsage]:
        """Start a new reasoning session."""
        task_message = self.format_task_message(task, mode, language, max_steps)
        messages = [
            {"role": "user", "content": task_message}
        ]
        parsed_response, token_usage, response = self.get_completion(messages)
        
        # Keep original raw response in message history
        messages.append({
            "role": "assistant",
            "content": response.choices[0].message.content  # Store raw content
        })
        return parsed_response, messages, token_usage
    
    def continue_reasoning(
        self,
        messages: list[Dict[str, str]],
        command: str = "CONTINUE"
    ) -> tuple[Dict[str, Any], list[Dict[str, str]], TokenUsage]:
        """Continue reasoning with a command."""
        messages.append({"role": "user", "content": command})
        parsed_response, token_usage, response = self.get_completion(messages)
        
        # Keep original raw response in message history
        messages.append({
            "role": "assistant",
            "content": response.choices[0].message.content  # Store raw content
        })
        return parsed_response, messages, token_usage 