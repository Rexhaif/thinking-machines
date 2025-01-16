import typer
import rich
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from pathlib import Path
from typing import Optional, Dict, Any
import json
import os
from enum import Enum
from dataclasses import dataclass
from datetime import datetime

from .llm import LLMClient
from .ui import (
    display_step, get_next_command, display_session_start, 
    display_error, calculate_step_cost, display_total_cost_summary
)
from .provider import ProviderManager

app = typer.Typer()
console = Console()

class Mode(str, Enum):
    EXPLORE_OPTIMAL = "EXPLORE_OPTIMAL"
    GO_SLIGHTLY_WRONG = "GO_SLIGHTLY_WRONG"
    GO_VERY_WRONG = "GO_VERY_WRONG"

class AutoMode(str, Enum):
    CONTINUE = "continue"
    VARY = "vary"
    WRONG = "wrong"

@dataclass
class SessionConfig:
    model: str
    api_key: str
    base_url: Optional[str]
    temperature: float
    max_tokens: int
    top_p: float
    enforce_json_response: bool

@dataclass
class ReasoningTrace:
    timestamp: datetime
    task: str
    mode: Mode
    language: str
    max_steps: int
    step_data: dict
    commands: list[str]
    total_costs: Dict[str, float]
    provider: Dict[str, Any]
    
    def to_dict(self):
        return {
            "timestamp": self.timestamp.isoformat(),
            "task": self.task,
            "mode": self.mode,
            "language": self.language,
            "max_steps": self.max_steps,
            "step_data": self.step_data,
            "commands": self.commands,
            "total_costs": self.total_costs,
            "provider": self.provider
        }

def save_trace(trace: ReasoningTrace, output_dir: Path, debug: bool = False):
    """Save reasoning trace to a file, optionally including detailed logs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"trace_{trace.timestamp.strftime('%Y%m%d_%H%M%S')}.json"
    
    # If not in debug mode, remove detailed token usage from steps
    if not debug:
        trace_dict = trace.to_dict()
        for step in trace_dict["step_data"]["steps"]:
            # Keep only essential token usage info
            step["token_usage"] = {
                "total_tokens": step["token_usage"]["total_tokens"],
                "cached_tokens": step["token_usage"]["cached_tokens"],
                "total_time": step["token_usage"]["total_time"]
            }
        with open(output_dir / filename, "w") as f:
            json.dump(trace_dict, f, indent=2, ensure_ascii=False)
    else:
        with open(output_dir / filename, "w") as f:
            json.dump(trace.to_dict(), f, indent=2, ensure_ascii=False)

@app.command()
def think(
    task: str = typer.Option(..., "--task", "-t", help="Task description"),
    mode: Mode = typer.Option(Mode.EXPLORE_OPTIMAL, "--mode", "-m", help="Reasoning mode"),
    language: str = typer.Option("English", "--language", "-l", help="Reasoning language"),
    max_steps: int = typer.Option(10, "--max-steps", "-s", help="Maximum number of steps"),
    provider: str = typer.Option("gpt-4o", "--provider", "-p", help="Provider configuration to use"),
    output_dir: Path = typer.Option(
        Path("traces"), "--output-dir", "-o", 
        help="Directory to save reasoning traces"
    ),
    auto: bool = typer.Option(False, "--auto", "-a", help="Run in automatic mode without user interaction"),
    auto_mode: AutoMode = typer.Option(
        AutoMode.CONTINUE, "--auto-mode", 
        help="Command variation in auto mode: continue (just CONTINUE), vary (mix of modes), wrong (only GO_VERY_WRONG)"
    ),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug mode to save API call details"),
):
    """
    Start an interactive reasoning session with specified parameters.
    """
    try:
        # Load provider configuration
        provider_manager = ProviderManager()
        provider_config = provider_manager.load_provider(provider)
        
        if not provider_config.api_key:
            console.print("[red]Error: API key not provided in provider config and not found in environment variables[/red]")
            raise typer.Exit(1)

        config = SessionConfig(
            model=provider_config.model,
            api_key=provider_config.api_key,
            base_url=provider_config.base_url,
            temperature=provider_config.temperature,
            max_tokens=provider_config.max_tokens,
            top_p=provider_config.top_p,
            enforce_json_response=provider_config.enforce_json_response
        )

        # Create debug directory only if debug mode is enabled
        debug_dir = None
        if debug:
            session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            debug_dir = output_dir / session_id / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)

        display_session_start(task, mode, language, max_steps, provider_config)
        
        llm = LLMClient(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            top_p=config.top_p,
            debug_dir=debug_dir,
            enforce_json_response=config.enforce_json_response
        )
        
        # Initialize total costs
        total_costs = {
            'input_cost': 0.0,
            'cached_cost': 0.0,
            'output_cost': 0.0,
            'total_cost': 0.0
        }
        
        # Start reasoning session
        step_data, messages, token_usage = llm.start_reasoning(task, mode, language, max_steps)
        
        # Simplify token usage data
        token_usage_dict = token_usage._asdict()
        simplified_token_usage = {
            'prompt_tokens': token_usage_dict['prompt_tokens'] if debug else None,
            'completion_tokens': token_usage_dict['completion_tokens'] if debug else None,
            'total_tokens': token_usage_dict['total_tokens'],
            'cached_tokens': token_usage_dict['cached_tokens'],
            'total_time': token_usage_dict['prompt_time'] + token_usage_dict['completion_time']
        }
        
        step_costs = calculate_step_cost(token_usage_dict, provider_config.pricing)
        display_step(step_data, current_step=1, max_steps=max_steps, token_usage=token_usage_dict, pricing=provider_config.pricing)
        
        # Update total costs
        for cost_type in total_costs:
            total_costs[cost_type] += step_costs[cost_type]
        
        # Store all steps and commands for the trace
        all_steps = [{"step": step_data, "token_usage": simplified_token_usage, "costs": step_costs}]
        commands = []
        current_step = 1
        
        # Continue until final solution
        while True:
            # Check if we have a final solution
            if step_data.get("is_final_result", False) or step_data.get("solution", {}).get("type") == "FINAL":
                break
                
            if auto:
                # Automatic command selection based on auto_mode
                if auto_mode == AutoMode.CONTINUE:
                    command = "CONTINUE"
                elif auto_mode == AutoMode.WRONG:
                    command = "GO_VERY_WRONG"
                else:  # VARY mode
                    import random
                    command = random.choice([
                        "CONTINUE",
                        "EXPLORE_OPTIMAL",
                        "GO_SLIGHTLY_WRONG",
                        "GO_VERY_WRONG"
                    ])
                console.print(f"\n[cyan]Auto-selecting command:[/cyan] {command}")
            else:
                command = get_next_command()
                if command.lower() == "exit":
                    break
            
            commands.append(command)
            step_data, messages, token_usage = llm.continue_reasoning(messages, command)
            current_step += 1
            
            # Simplify token usage data
            token_usage_dict = token_usage._asdict()
            simplified_token_usage = {
                'prompt_tokens': token_usage_dict['prompt_tokens'] if debug else None,
                'completion_tokens': token_usage_dict['completion_tokens'] if debug else None,
                'total_tokens': token_usage_dict['total_tokens'],
                'cached_tokens': token_usage_dict['cached_tokens'],
                'total_time': token_usage_dict['prompt_time'] + token_usage_dict['completion_time']
            }
            
            step_costs = calculate_step_cost(token_usage_dict, provider_config.pricing)
            display_step(step_data, current_step=current_step, max_steps=max_steps, token_usage=token_usage_dict, pricing=provider_config.pricing)
            
            # Update total costs
            for cost_type in total_costs:
                total_costs[cost_type] += step_costs[cost_type]
            
            all_steps.append({"step": step_data, "token_usage": simplified_token_usage, "costs": step_costs})
        
        # Display total cost breakdown
        display_total_cost_summary(total_costs)
        
        # Prepare provider info for trace
        provider_info = {
            "name": provider_config.name,
            "description": provider_config.description,
            "model": provider_config.model,
            "temperature": provider_config.temperature,
            "max_tokens": provider_config.max_tokens,
            "top_p": provider_config.top_p,
            "frequency_penalty": provider_config.frequency_penalty,
            "presence_penalty": provider_config.presence_penalty,
            "pricing": provider_config.pricing
        }
        
        # Save trace
        trace = ReasoningTrace(
            timestamp=datetime.now(),
            task=task,
            mode=mode,
            language=language,
            max_steps=max_steps,
            step_data={"steps": all_steps},
            commands=commands,
            total_costs=total_costs,
            provider=provider_info
        )
        save_trace(trace, output_dir, debug=debug)
        
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)

if __name__ == "__main__":
    app() 