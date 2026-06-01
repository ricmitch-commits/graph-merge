class OpenAIClient:
    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    def complete(self, prompt: str) -> str:
        import openai
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model=self._model_id,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content
