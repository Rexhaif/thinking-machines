from pathlib import Path
from typing import Optional, Dict, Any
import yaml
import os
from dataclasses import dataclass

@dataclass
class ProviderConfig:
    provider_type: str
    name: str
    description: str
    base_url: Optional[str]
    api_key: str
    model: str
    temperature: float
    max_tokens: int
    top_p: float
    frequency_penalty: float
    presence_penalty: float
    pricing: Dict[str, float]  # Pricing information per 1M tokens

class ProviderManager:
    def __init__(self, providers_dir: Path = Path("providers")):
        self.providers_dir = providers_dir
        self.default_provider = "gpt-4o"
        
    def _resolve_env_vars(self, value: str) -> str:
        """Resolve environment variables in string values."""
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            env_var = value[2:-1]
            return os.environ.get(env_var, "")
        return value
    
    def _process_config_values(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Process configuration values, resolving environment variables."""
        processed = {}
        for key, value in config.items():
            if isinstance(value, dict):
                processed[key] = self._process_config_values(value)
            else:
                processed[key] = self._resolve_env_vars(value)
        return processed
    
    def load_provider(self, provider_name: Optional[str] = None) -> ProviderConfig:
        """Load a provider configuration by name."""
        if provider_name is None:
            provider_name = self.default_provider
            
        config_file = self.providers_dir / f"{provider_name}.yml"
        if not config_file.exists():
            raise ValueError(f"Provider configuration '{provider_name}' not found at {config_file}")
            
        with open(config_file, "r") as f:
            config = yaml.safe_load(f)
            
        # Process environment variables
        config = self._process_config_values(config)
        
        # Validate provider type
        if config.get("provider_type") != "openai-compatible":
            raise ValueError(f"Unsupported provider type: {config.get('provider_type')}")
            
        # Create provider config
        return ProviderConfig(
            provider_type=config["provider_type"],
            name=config["name"],
            description=config["description"],
            base_url=config.get("base_url"),
            api_key=config["api_key"],
            model=config["model"],
            temperature=float(config.get("temperature", 0.7)),
            max_tokens=int(config.get("max_tokens", 2000)),
            top_p=float(config.get("top_p", 1.0)),
            frequency_penalty=float(config.get("frequency_penalty", 0.0)),
            presence_penalty=float(config.get("presence_penalty", 0.0)),
            pricing=config.get("pricing", {
                "input_tokens": 0.0,
                "cached_tokens": 0.0,
                "output_tokens": 0.0
            })
        )
    
    def list_providers(self) -> list[str]:
        """List available provider configurations."""
        self.providers_dir.mkdir(exist_ok=True)
        return [f.stem for f in self.providers_dir.glob("*.yml")] 