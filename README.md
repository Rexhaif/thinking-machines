# Thinking Machine CLI

Interactive CLI tool for exploring and testing reasoning capabilities of LLMs.

## Features

- Interactive reasoning sessions with step-by-step progress
- Multiple reasoning modes: optimal, slightly wrong, very wrong
- Automatic mode with configurable command selection
- Token usage tracking with caching statistics
- Detailed cost breakdown per step and session
- Configurable provider settings via YAML files
- Debug mode for detailed API call logging

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd thinking-machine

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

Basic usage with default settings:
```bash
python think.py --task "Your reasoning task here"
```

Advanced options:
```bash
python think.py \
  --task "Your task" \
  --mode EXPLORE_OPTIMAL \
  --language English \
  --max-steps 10 \
  --provider gpt-4o \
  --auto \
  --auto-mode vary \
  --debug
```

## Provider Configuration

Create a YAML file in the `providers` directory:
```yaml
provider_type: openai-compatible
name: your-provider
description: Your provider description

# Connection settings
base_url: null  # Optional, provider-specific base URL
api_key: ${API_KEY_ENV_VAR}  # Use environment variable

# Model settings
model: model-name
temperature: 0.7
max_tokens: 2000
top_p: 1.0
frequency_penalty: 0.0
presence_penalty: 0.0

# Pricing per 1M tokens (in USD)
pricing:
  input_tokens: 2.50
  cached_tokens: 1.25
  output_tokens: 10.00
```

## Output

The tool saves reasoning traces in JSON format with:
- Step-by-step reasoning process
- Token usage statistics
- Cost breakdown
- Provider configuration
- Command history

Debug mode provides additional details about API calls and token usage. 