from typing import Optional, Dict, Any, NamedTuple
import json
from openai import OpenAI
from pathlib import Path
from .ui import thinking_spinner
import time

class TokenUsage(NamedTuple):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int
    reasoning_tokens: int
    accepted_prediction_tokens: int
    rejected_prediction_tokens: int
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
        debug_dir: Optional[Path] = None
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
        
        # Load system prompt
        prompt_path = Path(__file__).parent.parent / "res" / "system.prompt.md"
        with open(prompt_path) as f:
            self.system_prompt = f.read()
            
    def _save_debug_info(self, messages: list[Dict[str, str]], response: Any, **kwargs):
        """Save debug information about the API call."""
        if not self.debug_dir:
            return
            
        self.call_counter += 1
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
            },
            "response": {
                "content": response.choices[0].message.content,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                    "prompt_tokens_details": getattr(response.usage, "prompt_tokens_details", None),
                    "completion_tokens_details": getattr(response.usage, "completion_tokens_details", None),
                }
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
    
    def get_completion(
        self,
        messages: list[Dict[str, str]],
        **kwargs
    ) -> tuple[Dict[str, Any], TokenUsage, Any]:
        """Get completion from the OpenAI API and parse the JSON response."""
        with thinking_spinner():
            start_time = time.time()
            full_messages = [{"role": "system", "content": self.system_prompt}, *messages]
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=full_messages,
                temperature=kwargs.get("temperature", self.temperature),
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
                top_p=kwargs.get("top_p", self.top_p),
                response_format={"type": "json_object"}
            )
            
            # Save debug information if enabled
            if self.debug_dir:
                self._save_debug_info(full_messages, response, **kwargs)
            
            end_time = time.time()
            
            # Calculate timing
            total_time = end_time - start_time
            usage = response.usage
            total_tokens = usage.total_tokens
            prompt_ratio = usage.prompt_tokens / total_tokens
            prompt_time = total_time * prompt_ratio
            completion_time = total_time * (1 - prompt_ratio)
            
            # Extract detailed token usage
            prompt_details = getattr(usage, 'prompt_tokens_details', None)
            completion_details = getattr(usage, 'completion_tokens_details', None)
            
            token_usage = TokenUsage(
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                cached_tokens=getattr(prompt_details, 'cached_tokens', 0) if prompt_details else 0,
                reasoning_tokens=getattr(completion_details, 'reasoning_tokens', 0) if completion_details else 0,
                accepted_prediction_tokens=getattr(completion_details, 'accepted_prediction_tokens', 0) if completion_details else 0,
                rejected_prediction_tokens=getattr(completion_details, 'rejected_prediction_tokens', 0) if completion_details else 0,
                prompt_time=prompt_time,
                completion_time=completion_time
            )
            
            try:
                parsed_response = json.loads(response.choices[0].message.content)
                return parsed_response, token_usage, response
            except json.JSONDecodeError:
                raise ValueError("Failed to parse JSON response from LLM")
    
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