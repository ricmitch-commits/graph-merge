class AnthropicClient:
    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    def complete(self, prompt: str) -> str:
        import anthropic
        client = anthropic.Anthropic()
        message = client.messages.create(
            model=self._model_id,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
