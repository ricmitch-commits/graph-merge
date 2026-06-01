class VertexClient:
    """Google Vertex AI client supporting both Gemini and Claude models.

    Authentication: run `gcloud auth application-default login` or set
    GOOGLE_APPLICATION_CREDENTIALS to a service account key file.

    Environment variables:
      VERTEX_PROJECT_ID   - GCP project ID (required)
      VERTEX_REGION  - GCP region (default: us-central1)

    Model routing:
      vertex/gemini-*  → vertexai.generative_models.GenerativeModel
      vertex/claude-*  → anthropic.AnthropicVertex
    """

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    def complete(self, prompt: str) -> str:
        import os
        project = os.environ.get("VERTEX_PROJECT_ID")
        location = os.environ.get("VERTEX_REGION", "us-central1")

        if self._model_id.startswith("claude"):
            return self._complete_claude(prompt, project, location)
        return self._complete_gemini(prompt, project, location)

    def _complete_claude(self, prompt: str, project: str | None, location: str) -> str:
        from anthropic import AnthropicVertex
        kwargs = {"region": location}
        if project:
            kwargs["project_id"] = project
        client = AnthropicVertex(**kwargs)
        message = client.messages.create(
            model=self._model_id,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    def _complete_gemini(self, prompt: str, project: str | None, location: str) -> str:
        import vertexai
        from vertexai.generative_models import GenerativeModel
        vertexai.init(project=project, location=location)
        model = GenerativeModel(self._model_id)
        response = model.generate_content(prompt)
        return response.text
