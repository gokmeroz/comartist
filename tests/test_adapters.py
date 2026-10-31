"""Model adapters: request shape, error mapping, fallback, and factory wiring. No network."""

from typing import Any

import pytest
from pydantic import SecretStr

from comartist.adapters import (
    ChatMessage,
    ImageReference,
    ImageRequest,
    ModelError,
    ModelErrorKind,
    TextRequest,
    build_image_model,
    build_text_model,
)
from comartist.adapters.fake import FakeTextModel
from comartist.adapters.fallback import FallbackText
from comartist.adapters.openai_compatible import (
    ChatCompletionsText,
    ImagesEndpointImage,
    ResponsesImage,
    ResponsesText,
)
from comartist.config import EndpointSettings, MetaSettings, ModelPrice

KEY = SecretStr("sk-test-secret")
REQUEST = TextRequest(
    messages=[
        ChatMessage(role="system", content="Be brief."),
        ChatMessage(role="user", content="Hello"),
    ]
)
WONDER_PRICE = ModelPrice(input_per_m_tokens=4.0, output_per_m_tokens=20.0)


class FakeTransport:
    def __init__(self, *replies: tuple[int, dict[str, Any]] | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    def post_json(self, url, payload, headers, timeout_s):
        self.calls.append((url, payload, headers))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def responses_body(text: str) -> dict[str, Any]:
    return {
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": text}]},
        ],
        "usage": {"input_tokens": 1_000, "output_tokens": 500},
    }


def chat_body(text: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }


def responses_text(transport: FakeTransport) -> ResponsesText:
    return ResponsesText(
        "meta", "muse-wonder-1.0", "https://api.example/v1/", KEY, transport, price=WONDER_PRICE
    )


def test_responses_text_request_shape_and_cost() -> None:
    transport = FakeTransport((200, responses_body("Hi there")))
    result = responses_text(transport).complete(REQUEST.model_copy(update={"json_mode": True}))

    url, payload, headers = transport.calls[0]
    assert url == "https://api.example/v1/responses"
    assert payload["model"] == "muse-wonder-1.0"
    assert payload["input"] == [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": [{"type": "input_text", "text": "Hello"}]},
    ]
    assert payload["stream"] is False
    assert payload["text"] == {"format": {"type": "json_object"}}
    assert headers["Authorization"] == "Bearer sk-test-secret"
    assert result.text == "Hi there"
    assert (result.cost.prompt_tokens, result.cost.completion_tokens) == (1_000, 500)
    assert result.cost.usd == pytest.approx(0.004 + 0.01)


def test_chat_completions_text_without_price_has_unknown_cost() -> None:
    transport = FakeTransport((200, chat_body("Hi")))
    client = ChatCompletionsText("fireworks", "llama", "https://fw.example/v1", KEY, transport)
    result = client.complete(REQUEST)

    assert transport.calls[0][0] == "https://fw.example/v1/chat/completions"
    assert transport.calls[0][1]["messages"][1] == {"role": "user", "content": "Hello"}
    assert (result.text, result.cost.prompt_tokens, result.cost.usd) == ("Hi", 7, None)


@pytest.mark.parametrize(
    ("status", "message", "kind"),
    [
        (401, "bad key", ModelErrorKind.AUTH),
        (402, "payment required", ModelErrorKind.QUOTA),
        (429, "slow down", ModelErrorKind.RATE_LIMIT),
        (429, "insufficient_quota", ModelErrorKind.QUOTA),
        (503, "overloaded", ModelErrorKind.TRANSIENT),
        (400, "bad param", ModelErrorKind.BAD_REQUEST),
    ],
)
def test_http_errors_map_to_kinds(status: int, message: str, kind: ModelErrorKind) -> None:
    transport = FakeTransport((status, {"error": {"message": message}}))
    with pytest.raises(ModelError) as caught:
        responses_text(transport).complete(REQUEST)
    assert caught.value.kind is kind
    assert "sk-test-secret" not in str(caught.value)


def test_network_failure_is_transient() -> None:
    with pytest.raises(ModelError) as caught:
        responses_text(FakeTransport(TimeoutError("timed out"))).complete(REQUEST)
    assert caught.value.kind is ModelErrorKind.TRANSIENT


@pytest.mark.parametrize("body", [{}, {"output": []}, responses_body("   ")])
def test_unusable_completion_is_rejected(body: dict[str, Any]) -> None:
    with pytest.raises(ModelError) as caught:
        responses_text(FakeTransport((200, body))).complete(REQUEST)
    assert caught.value.kind is ModelErrorKind.BAD_RESPONSE


def test_token_budget_spent_on_reasoning_is_reported() -> None:
    # Shape observed live from muse-wonder-1.0 with max_output_tokens=50.
    body = {
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output": [{"type": "reasoning", "status": "incomplete", "summary": []}],
        "usage": {"input_tokens": 15, "output_tokens": 50},
    }
    with pytest.raises(ModelError, match="Ran out of tokens"):
        responses_text(FakeTransport((200, body))).complete(REQUEST)


def responses_image(transport: FakeTransport) -> ResponsesImage:
    return ResponsesImage(
        "meta", "muse-image-1.0", "https://api.example/v1", KEY, transport,
        price=ModelPrice(per_image=0.01),
    )


@pytest.mark.parametrize(
    "body",
    [
        # Documented images-endpoint shape.
        {"data": [{"b64_json": "UklGR"}], "output_format": "webp"},
        # Plausible Responses-API shapes.
        {"output": [{"type": "image_generation_call", "result": "UklGR"}], "output_format": "webp"},
        {
            "output": [
                {"type": "message", "content": [{"type": "output_image", "image_url": "data:image/webp;base64,UklGR"}]}
            ],
            "output_format": "webp",
        },
    ],
)
def test_image_parses_known_shapes(body: dict[str, Any]) -> None:
    body["usage"] = {"input_tokens": 9831, "output_tokens": 749}
    result = responses_image(FakeTransport((200, body))).generate(ImageRequest(prompt="A fox"))
    assert result.image_b64 == "UklGR" and result.url is None
    assert result.mime_type == "image/webp"
    assert (result.cost.images, result.cost.usd) == (1, 0.01)


def test_image_prompt_only_sends_plain_input_and_size() -> None:
    transport = FakeTransport((200, {"data": [{"b64_json": "x"}]}))
    responses_image(transport).generate(ImageRequest(prompt="A fox"))
    url, payload, _ = transport.calls[0]
    assert url == "https://api.example/v1/responses"
    assert payload == {
        "model": "muse-image-1.0",
        "input": "A fox",
        "tools": [{"type": "image_generation", "size": "1024x1024"}],
    }


def test_image_references_are_sent_in_order_with_captions() -> None:
    transport = FakeTransport((200, {"data": [{"b64_json": "x"}]}))
    responses_image(transport).generate(
        ImageRequest(
            prompt="Matt waves at Andy.",
            references=[
                ImageReference(image_url="data:image/png;base64,AAA", caption="Matt:"),
                ImageReference(image_url="https://example.com/andy.png"),
            ],
        )
    )
    assert transport.calls[0][1]["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Matt:"},
                {"type": "input_image", "image_url": "data:image/png;base64,AAA"},
                {"type": "input_image", "image_url": "https://example.com/andy.png"},
                {"type": "input_text", "text": "Matt waves at Andy."},
            ],
        }
    ]


def test_image_without_image_is_rejected() -> None:
    with pytest.raises(ModelError) as caught:
        responses_image(FakeTransport((200, responses_body("I can't draw that")))).generate(
            ImageRequest(prompt="x")
        )
    assert caught.value.kind is ModelErrorKind.BAD_RESPONSE


def test_images_endpoint_rejects_references() -> None:
    client = ImagesEndpointImage("fw", "img", "https://fw.example/v1", KEY, FakeTransport())
    with pytest.raises(ModelError) as caught:
        client.generate(ImageRequest(prompt="x", references=[ImageReference(image_url="u")]))
    assert caught.value.kind is ModelErrorKind.BAD_REQUEST


def test_fallback_moves_on_for_quota() -> None:
    quota = ModelError(ModelErrorKind.QUOTA, "out of credits", "meta")
    chain = FallbackText(
        [FakeTextModel([quota], provider="meta"), FakeTextModel(["backup"], provider="fireworks")]
    )
    result = chain.complete(REQUEST)
    assert (result.text, result.provider) == ("backup", "fireworks")
    assert [e.kind for e in chain.errors] == [ModelErrorKind.QUOTA]


def test_fallback_does_not_hide_bad_requests() -> None:
    backup = FakeTextModel(["backup"])
    chain = FallbackText([FakeTextModel([ModelError(ModelErrorKind.BAD_REQUEST, "x")]), backup])
    with pytest.raises(ModelError) as caught:
        chain.complete(REQUEST)
    assert caught.value.kind is ModelErrorKind.BAD_REQUEST
    assert backup.requests == []


def test_fallback_reports_when_every_provider_fails() -> None:
    down = ModelError(ModelErrorKind.TRANSIENT, "down")
    chain = FallbackText([FakeTextModel([down]), FakeTextModel([down])], retries=0)
    with pytest.raises(ModelError, match="All providers failed"):
        chain.complete(REQUEST)
    assert len(chain.errors) == 2


def endpoints(fireworks_key: SecretStr | None) -> dict[str, EndpointSettings]:
    return {
        "meta": MetaSettings(api_key=KEY, base_url="https://meta.example/v1"),
        "fireworks": EndpointSettings(
            api_key=fireworks_key,
            base_url="https://fw.example/v1",
            text_model_ids={"Llama": "llama-70b"},
            image_style="flux_workflow",
            image_model_ids={"FLUX": "flux-schnell"},
        ),
    }


def no_sleep(_: float) -> None:
    pass


def test_rate_limit_is_retried_on_the_same_provider_with_backoff() -> None:
    waits: list[float] = []
    transport = FakeTransport(
        (429, {"error": {"message": "slow down"}}),
        (503, {"error": {"message": "overloaded"}}),
        (200, responses_body("ok")),
    )
    model = build_text_model("meta", "Muse Wonder", endpoints(None), transport, sleep=waits.append)
    assert model.complete(REQUEST).provider == "meta"
    assert waits == [2.0, 4.0]
    assert {call[0] for call in transport.calls} == {"https://meta.example/v1/responses"}


def test_retries_exhausted_then_falls_back() -> None:
    down = (503, {"error": {"message": "overloaded"}})
    transport = FakeTransport(down, down, down, (200, chat_body("backup")))
    model = build_text_model("meta", "Muse Wonder", endpoints(SecretStr("fw")), transport, sleep=no_sleep)
    assert model.complete(REQUEST).provider == "fireworks"
    assert len(transport.calls) == 4


def test_quota_is_not_retried() -> None:
    transport = FakeTransport((402, {"error": {"message": "no credits"}}))
    model = build_text_model("meta", "Muse Wonder", endpoints(None), transport, sleep=no_sleep)
    with pytest.raises(ModelError, match="All providers failed"):
        model.complete(REQUEST)
    assert len(transport.calls) == 1


def test_image_falls_back_to_flux_and_counts_dropped_references() -> None:
    transport = FakeTransport(
        (402, {"error": {"message": "no credits"}}),
        (200, {"data": [{"b64_json": "x"}], "output_format": "jpeg"}),
    )
    model = build_image_model("meta", "Muse Image", endpoints(SecretStr("fw")), transport, sleep=no_sleep)
    result = model.generate(
        ImageRequest(prompt="Matt waves.", seed=7, references=[ImageReference(image_url="u")])
    )
    url, payload, _ = transport.calls[1]
    assert url == "https://fw.example/v1/workflows/flux-schnell/text_to_image"
    assert payload == {"prompt": "Matt waves.", "aspect_ratio": "1:1", "seed": 7}
    assert (result.provider, result.ignored_references, result.mime_type) == ("fireworks", 1, "image/jpeg")
    assert result.cost.usd is None  # no FLUX price configured


def test_meta_defaults_match_the_docs() -> None:
    meta = MetaSettings(_env_file=None)
    assert meta.base_url == "https://api.meta.ai/v1"
    assert meta.api_style == "responses"
    assert meta.text_model_ids == {"Muse Wonder": "muse-wonder-1.0"}
    assert meta.image_model_ids == {"Muse Image": "muse-image-1.0"}


def test_factory_falls_back_to_fireworks_when_meta_is_out_of_credits() -> None:
    transport = FakeTransport((402, {"error": {"message": "no credits"}}), (200, chat_body("ok")))
    model = build_text_model("meta", "Muse Wonder", endpoints(SecretStr("fw")), transport)

    result = model.complete(REQUEST)
    assert result.provider == "fireworks" and result.model == "llama-70b"
    assert [call[0] for call in transport.calls] == [
        "https://meta.example/v1/responses",
        "https://fw.example/v1/chat/completions",
    ]


def test_factory_builds_meta_clients_with_prices() -> None:
    transport = FakeTransport((200, responses_body("ok")), (200, {"data": [{"b64_json": "x"}]}))
    text = build_text_model("meta", "Muse Wonder", endpoints(None), transport)
    assert text.complete(REQUEST).cost.usd == pytest.approx(0.014)
    image = build_image_model("meta", "Muse Image", endpoints(None), transport)
    assert image.generate(ImageRequest(prompt="x")).cost.usd == 0.01


def test_factory_config_errors() -> None:
    with pytest.raises(ModelError) as caught:
        build_text_model("meta", "Muse Spark", endpoints(None))
    assert caught.value.kind is ModelErrorKind.CONFIG

    missing_key = endpoints(None)
    missing_key["meta"].api_key = None
    with pytest.raises(ModelError, match="API key is not set"):
        build_image_model("meta", "Muse Image", missing_key)

    with pytest.raises(ModelError, match="not implemented"):
        build_text_model("modal", "Llama", endpoints(None))


def test_stub_provider_is_offline() -> None:
    assert build_text_model("stub", "stub-text").complete(REQUEST).cost.usd == 0.0
    assert build_image_model("stub", "stub-image").generate(ImageRequest(prompt="x")).image_b64


def test_settings_read_keys_from_dotenv(tmp_path, monkeypatch) -> None:
    from comartist.config import PROVIDERS

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("COMARTIST_META_API_KEY", raising=False)
    assert not PROVIDERS["meta"].key_present()

    (tmp_path / ".env").write_text("COMARTIST_META_API_KEY=from-dotenv\nUNRELATED=1\n")
    assert MetaSettings().api_key.get_secret_value() == "from-dotenv"
    assert PROVIDERS["meta"].key_present()
