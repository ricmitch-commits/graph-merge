import os


class VertexClient:
    """Google Vertex AI client supporting both Gemini and Claude models.

    Authentication: run `gcloud auth application-default login` or set
    GOOGLE_APPLICATION_CREDENTIALS to a service account key file.

    Environment variables:
      VERTEX_PROJECT_ID            - GCP project ID (required)
      VERTEX_REGION                - GCP region
      CLOUD_ML_REGION              - Anthropic SDK native region env var (fallback)
      ANTHROPIC_VERTEX_PROJECT_ID  - Anthropic SDK native project env var (fallback)

    Model routing:
      vertex/gemini-*  → vertexai.generative_models.GenerativeModel
      vertex/claude-*  → anthropic.AnthropicVertex
    """

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    def complete(self, prompt: str) -> str:
        project = os.environ.get("VERTEX_PROJECT_ID")
        # Support both our env var and the Anthropic SDK's native one
        region = (
            os.environ.get("VERTEX_REGION")
            or os.environ.get("CLOUD_ML_REGION")
            or "us-central1"
        )
        print(f"[vertex] region={region!r} project={project!r} model={self._model_id!r}")

        if self._model_id.startswith("claude"):
            return self._complete_claude(prompt, project, region)
        return self._complete_gemini(prompt, project, region)

    def _complete_claude(self, prompt: str, project: str | None, region: str) -> str:
        from anthropic import AnthropicVertex
        kwargs: dict = {"region": region}
        if project:
            kwargs["project_id"] = project
        client = AnthropicVertex(**kwargs)
        message = client.messages.create(
            model=self._model_id,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    def _complete_gemini(self, prompt: str, project: str | None, region: str) -> str:
        import vertexai
        from vertexai.generative_models import GenerativeModel
        vertexai.init(project=project, location=region)
        model = GenerativeModel(self._model_id)
        response = model.generate_content(prompt)
        return response.text
