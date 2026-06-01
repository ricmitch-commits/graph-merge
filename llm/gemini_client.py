class GeminiClient:
    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    def complete(self, prompt: str) -> str:
        import google.generativeai as genai
        model = genai.GenerativeModel(self._model_id)
        response = model.generate_content(prompt)
        return response.text
