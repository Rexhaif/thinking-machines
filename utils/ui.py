from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.syntax import Syntax
from rich.progress import Progress, BarColumn, TextColumn, SpinnerColumn
from rich.live import Live
from rich.spinner import Spinner
from rich.progress_bar import ProgressBar
from rich.style import Style
from rich.status import Status
from typing import Dict, Any, Optional
from contextlib import contextmanager

console = Console()

@contextmanager
def thinking_spinner(message: str = "Thinking"):
    """Display a spinner while waiting for API response."""
    # Use point spinner style for a clean, minimal look
    spinner_style = "point"
    
    # Create a fancy status with minimal symbols
    prefix = "◈"
    suffix = "◇"
    
    # Use monochromatic colors for clean look
    message_color = "bright_white"
    spinner_color = "bright_white"
    
    fancy_message = f"[{message_color}]{prefix} {message}... {suffix}[/{message_color}]"
    
    with Status(
        fancy_message,
        spinner=spinner_style,
        spinner_style=spinner_color,
        refresh_per_second=20  # Smoother animation
    ) as status:
        try:
            yield status
        finally:
            # Add a completion indicator with filled diamond
            status.update(f"[{message_color}]{prefix} Done ◆[/{message_color}]")

def create_progress_bar(value: int | str, total: int | str, color: str = "cyan") -> str:
    """Create a progress bar string."""
    # Convert to integers
    value = int(value)
    total = int(total)
    
    width = 20
    filled = int(width * (value / total))
    bar = f"[{color}]{'█' * filled}{'░' * (width - filled)}[/{color}]"
    return f"{bar} {value}/{total}"

def calculate_step_cost(token_usage: Dict[str, Any], pricing: Dict[str, float]) -> Dict[str, float]:
    """Calculate the cost breakdown of a step based on token usage and pricing."""
    effective_tokens = token_usage['prompt_tokens'] - token_usage['cached_tokens']
    
    # Calculate costs per token type (converting from per 1M tokens to per token)
    input_cost = (effective_tokens * pricing['input_tokens']) / 1_000_000
    cached_cost = (token_usage['cached_tokens'] * pricing['cached_tokens']) / 1_000_000
    output_cost = (token_usage['completion_tokens'] * pricing['output_tokens']) / 1_000_000
    
    return {
        'input_cost': input_cost,
        'cached_cost': cached_cost,
        'output_cost': output_cost,
        'total_cost': input_cost + cached_cost + output_cost
    }

def create_token_stats(token_usage: Dict[str, Any], pricing: Optional[Dict[str, float]] = None) -> Table:
    """Create a table with token usage statistics."""
    stats = Table.grid(padding=(0, 2))
    
    # Calculate speeds
    prompt_speed = token_usage['prompt_tokens'] / token_usage['prompt_time'] if token_usage['prompt_time'] > 0 else 0
    completion_speed = token_usage['completion_tokens'] / token_usage['completion_time'] if token_usage['completion_time'] > 0 else 0
    
    # Format speeds with proper units
    def format_speed(speed: float) -> str:
        if speed >= 1000:
            return f"{speed/1000:.1f}k tok/s"
        return f"{speed:.1f} tok/s"
    
    # Main token usage row
    stats.add_row(
        "[bold]Token Usage:[/bold]",
        f"[cyan]Prompt:[/cyan] {token_usage['prompt_tokens']} ({format_speed(prompt_speed)})",
        f"[green]Completion:[/green] {token_usage['completion_tokens']} ({format_speed(completion_speed)})",
        f"[yellow]Total:[/yellow] {token_usage['total_tokens']}"
    )
    
    # Cache info
    cache_ratio = token_usage['cached_tokens'] / token_usage['prompt_tokens'] * 100 if token_usage['prompt_tokens'] > 0 else 0
    stats.add_row(
        "[bold]Cache Info:[/bold]",
        f"[cyan]Cached:[/cyan] {token_usage['cached_tokens']} ({cache_ratio:.1f}%)",
        f"[yellow]Effective:[/yellow] {token_usage['prompt_tokens'] - token_usage['cached_tokens']}"
    )
    
    # Cost information if pricing is provided
    if pricing:
        costs = calculate_step_cost(token_usage, pricing)
        stats.add_row(
            "[bold magenta]Cost:[/bold magenta]",
            f"[magenta]Input: ${costs['input_cost']:.4f}[/magenta]",
            f"[magenta]Cached: ${costs['cached_cost']:.4f}[/magenta]",
            f"[magenta]Output: ${costs['output_cost']:.4f}[/magenta]"
        )
        stats.add_row(
            "[bold magenta]Total:[/bold magenta]",
            f"[bold magenta]${costs['total_cost']:.4f}[/bold magenta]"
        )
        return stats
    
    return stats

def display_step(
    step_data: Dict[str, Any], 
    current_step: int, 
    max_steps: int, 
    token_usage: Optional[Dict[str, Any]] = None,
    pricing: Optional[Dict[str, float]] = None
):
    """Display a reasoning step with rich formatting."""
    # Header with step info
    header = Table.grid(padding=(0, 1))
    
    # Format step counter
    if current_step > max_steps:
        step_counter = f"[bold red underline]Step {current_step}/{max_steps}[/bold red underline]"
        step_style = "red"
    else:
        step_counter = f"[cyan]Step {current_step}/{max_steps}[/cyan]"
        step_style = "cyan"
    
    # Create progress indicators
    step_progress = create_progress_bar(current_step, max_steps, step_style)
    confidence_progress = create_progress_bar(
        step_data.get('confidence_level', 1),
        5,
        "yellow"
    )
    
    header.add_row(
        step_counter,
        f"[yellow]Confidence:[/yellow] {confidence_progress}",
        f"[green]Language: {step_data['reasoning_language']}[/green]"
    )
    console.print(header)
    
    # Display token usage if available
    if token_usage:
        stats = create_token_stats(token_usage, pricing)
        if stats is not None:
            console.print(stats)
    
    # Step title with spinner
    console.print(Panel(
        f"[bold]{step_data['step_title']}[/bold]",
        style="blue",
        subtitle="🤔" if step_data.get('solution', {}).get('type', 'NONE') == "NONE" else "✨"
    ))
    
    # Main reasoning
    console.print(Markdown(step_data['step_text']))
    
    # Solution if present
    solution = step_data.get('solution', {})
    if solution.get('type', 'NONE') != "NONE":
        completeness = solution.get('completeness', 0)
        solution_progress = create_progress_bar(completeness, 100, "green")
        
        solution_panel = Panel(
            Markdown(solution['content']),
            title=f"[bold green]Solution ({solution['type']})[/bold green]",
            subtitle=f"Completeness: {solution_progress}",
            border_style="green"
        )
        console.print(solution_panel)
    
    console.print()

def get_next_command() -> str:
    """Get the next command from user input."""
    choices = [
        ("1", "CONTINUE"),
        ("2", "EXPLORE_OPTIMAL"),
        ("3", "GO_SLIGHTLY_WRONG"),
        ("4", "GO_VERY_WRONG"),
        ("5", "REASONING_LANGUAGE"),
        ("6", "EXIT")
    ]
    
    # Create a menu panel with choices
    menu_items = []
    for num, cmd in choices:
        menu_items.append(f"[cyan]{num}[/cyan] • {cmd}")
    menu = Panel(
        "\n".join(menu_items),
        title="[bold yellow]Available Commands[/bold yellow]",
        border_style="yellow",
        padding=(0, 2)
    )
    console.print(menu)
    
    while True:
        choice = Prompt.ask("[yellow]Choice[/yellow]", default="1").strip()
        
        # Handle numeric choice
        if choice.isdigit() and 1 <= int(choice) <= len(choices):
            command = choices[int(choice) - 1][1]
        else:
            # Handle full command text
            valid_commands = [cmd for _, cmd in choices]
            if choice.upper() in valid_commands:
                command = choice.upper()
            else:
                console.print("[red]Invalid choice[/red]")
                continue
        
        if command == "REASONING_LANGUAGE":
            language = Prompt.ask("[yellow]Language[/yellow]")
            return f"REASONING_LANGUAGE {language}"
        
        return command

def display_session_start(
    task: str,
    mode: str,
    language: str,
    max_steps: int,
    provider_config: Any
):
    """Display session initialization information."""
    # Create a fancy header
    console.print("\n")
    console.print("[bold cyan]╭─" + "─" * 50 + "─╮[/bold cyan]")
    console.print("[bold cyan]│[/bold cyan]" + " " * 15 + "[bold yellow]Thinking Machine Session[/bold yellow]" + " " * 13 + "[bold cyan]│[/bold cyan]")
    console.print("[bold cyan]╰─" + "─" * 50 + "─╯[/bold cyan]")
    console.print("\n")
    
    # Create provider info panel
    provider_info = Panel.fit(
        f"[bold blue]Provider:[/bold blue] {provider_config.name}\n"
        f"[blue]{provider_config.description}[/blue]\n\n"
        f"[dim]Model:[/dim] {provider_config.model}\n"
        f"[dim]Temperature:[/dim] {provider_config.temperature}\n"
        f"[dim]Max Tokens:[/dim] {provider_config.max_tokens}",
        title="[bold cyan]Provider Configuration[/bold cyan]",
        border_style="cyan"
    )
    
    # Create session info panel
    session_info = Panel.fit(
        f"[bold green]Session Configuration[/bold green]\n\n"
        f"[cyan]Task:[/cyan] {task}\n"
        f"[cyan]Mode:[/cyan] {mode}\n"
        f"[cyan]Language:[/cyan] {language}\n"
        f"[cyan]Max Steps:[/cyan] {max_steps}",
        border_style="green",
        padding=(1, 2)
    )
    
    # Display both panels
    console.print(provider_info)
    console.print()
    console.print(session_info)
    console.print()

def display_error(message: str):
    """Display an error message."""
    console.print(Panel(
        f"[bold red]{message}[/bold red]",
        title="[bold red]Error[/bold red]",
        border_style="red"
    )) 

def display_total_cost_summary(total_costs: Dict[str, float]):
    """Display a detailed summary of total costs."""
    console.print(
        f"\n[magenta]Cost Summary:[/magenta] "
        f"[magenta]Input: ${total_costs['input_cost']:.4f}[/magenta] | "
        f"[magenta]Cached: ${total_costs['cached_cost']:.4f}[/magenta] | "
        f"[magenta]Output: ${total_costs['output_cost']:.4f}[/magenta] | "
        f"[bold magenta]Total: ${total_costs['total_cost']:.4f}[/bold magenta]\n"
    ) 