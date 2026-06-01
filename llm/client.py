from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...


class MockLLMClient:
    def __init__(self, response: str) -> None:
        self._response = response
        self.call_count = 0
        self.last_prompt: str | None = None

    def complete(self, prompt: str) -> str:
        self.call_count += 1
        self.last_prompt = prompt
        return self._response


def create_client(model_spec: str) -> LLMClient:
    provider, _, model_id = model_spec.partition("/")
    if not model_id:
        raise ValueError(
            f"Invalid model spec '{model_spec}': expected '<provider>/<model-id>'"
        )
    if provider == "claude":
        from llm.anthropic_client import AnthropicClient
        return AnthropicClient(model_id)
    if provider == "openai":
        from llm.openai_client import OpenAIClient
        return OpenAIClient(model_id)
    if provider == "gemini":
        from llm.gemini_client import GeminiClient
        return GeminiClient(model_id)
    if provider == "vertex":
        from llm.vertex_client import VertexClient
        return VertexClient(model_id)
    raise ValueError(
        f"Unknown provider '{provider}': expected claude, openai, gemini, or vertex"
    )
