from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

from openai import Stream
from openai.types.realtime.realtime_conversation_item_assistant_message import (
    Content as AssistantContent,
)
from openai.types.responses import (
    ResponseCompletedEvent,
    ResponseErrorEvent,
    ResponseFailedEvent,
    ResponseFunctionToolCall,
    ResponseIncompleteEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputMessage,
    ResponseReasoningItem,
    ResponseTextDeltaEvent,
)

from speech_to_speech.LLM.base_openai_compatible_language_model import (
    WARMUP_MAX_RETRIES,
    AssistantMessage,
    BaseOpenAICompatibleHandler,
    ProviderEvent,
    ProviderResponseEnd,
    TextDelta,
    ToolCall,
    Usage,
)
from speech_to_speech.LLM.chat import Chat
from speech_to_speech.LLM.chat_completions_language_model import (
    _build_chat_optional_kwargs,
    _chat_messages,
    _iter_chat_response_events,
    _iter_chat_stream_events,
    _request_chat_completions,
)
from speech_to_speech.LLM.compaction_prompt import CompactGenerateFn
from speech_to_speech.utils.utils import _generate_id

logger = logging.getLogger(__name__)


def _response_end(response: Any, *, status: str | None = None) -> ProviderResponseEnd:
    status = status or getattr(response, "status", None)
    if status == "incomplete":
        reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
        if reason not in ("max_output_tokens", "content_filter"):
            # Compatible servers may omit the reason or use an extension.
            # Preserve the status without inventing a Realtime reason.
            reason = None
        return ProviderResponseEnd(status="incomplete", reason=reason)
    if status == "failed":
        error = getattr(response, "error", None)
        return ProviderResponseEnd(status="failed", error=getattr(error, "message", None))
    return ProviderResponseEnd()


class ResponsesApiModelHandler(BaseOpenAICompatibleHandler):
    """LLM handler that talks to an OpenAI ``/v1/responses`` server."""

    @classmethod
    def _build_extra_body(
        cls,
        base_url: str | None,
        disable_thinking: bool,
        reasoning_effort: str | None,
    ) -> dict[str, Any] | None:
        """Disable chat-template thinking on the Responses path for providers that
        read ``enable_thinking`` directly.

        DashScope/Bailian's ``/responses`` compatibility layer ignores
        ``reasoning: {effort: ...}`` for thinking control and defaults
        ``enable_thinking=True``, which then conflicts with an assistant response
        prefill (400 "Assistant response prefill is incompatible with
        enable_thinking"). Sending ``chat_template_kwargs.enable_thinking=false``
        explicitly turns it off for those providers; the official OpenAI server
        rejects the key, so we skip it there. ``reasoning.effort`` (applied
        separately via :meth:`_reasoning_kwargs`) remains for providers that
        prefer that knob.
        """
        if base_url is None or cls._is_official_openai(base_url):
            return None
        if disable_thinking:
            return {"chat_template_kwargs": {"enable_thinking": False}}
        return None

    def _reasoning_kwargs(self) -> dict[str, Any]:
        if self.reasoning_effort is None:
            return {}
        return {"reasoning": {"effort": self.reasoning_effort}}

    def warmup(self) -> None:
        logger.info(f"Warming up {self.__class__.__name__}")
        start = time.time()
        self.client.with_options(max_retries=WARMUP_MAX_RETRIES).responses.create(
            model=self.model_name,
            input=[
                {
                    "type": "message",
                    "role": "system",
                    "content": [{"type": "input_text", "text": "You are a helpful assistant"}],
                },
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Hello"}]},
            ],
            timeout=self.request_timeout,
            **self._reasoning_kwargs(),
        )
        end = time.time()
        logger.info(f"{self.__class__.__name__}:  warmed up! time: {(end - start):.3f} s")

    def _build_compaction_generate_fn(self) -> CompactGenerateFn:
        """Return a generate fn that calls the Responses API for compaction."""
        client = self.client
        model_name = self.model_name
        timeout = self.request_timeout
        reasoning_kwargs = self._reasoning_kwargs()

        def generate(system: str, user: str) -> str:
            response = client.responses.create(
                model=model_name,
                input=[
                    {
                        "type": "message",
                        "role": "system",
                        "content": [{"type": "input_text", "text": system}],
                    },
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": user}],
                    },
                ],
                timeout=timeout,
                **reasoning_kwargs,
            )
            return response.output_text

        return generate

    def _build_audio_optional_kwargs(
        self,
        response: Any,
        req_tools: Any,
        req_tool_choice: Any,
    ) -> dict[str, Any]:
        kwargs = _build_chat_optional_kwargs(req_tools, req_tool_choice)
        max_tokens = getattr(response, "max_output_tokens", None) if response is not None else None
        kwargs.setdefault("max_tokens", max_tokens or self.audio_max_tokens)
        kwargs.setdefault("temperature", self.audio_temperature)
        return kwargs

    def _serialize_audio(self, active_chat: Chat) -> list[dict[str, Any]]:
        return _chat_messages(active_chat, audio_content_type=self.audio_content_type)

    def _request_audio(
        self,
        api_input: list[dict[str, Any]],
        optional_kwargs: dict[str, Any],
    ) -> Any:
        return _request_chat_completions(
            client=self.client,
            model_name=self.model_name,
            messages=api_input,
            stream=self.stream,
            extra_body=self._extra_body,
            timeout=self.request_timeout,
            optional_kwargs=optional_kwargs,
        )

    def _iter_audio_events(self, api_response: Any) -> Iterator[ProviderEvent]:
        if self.stream:
            yield from _iter_chat_stream_events(api_response)
        else:
            yield from _iter_chat_response_events(api_response)

    # ── base hooks ──────────────────────────────────────────────────────────--

    def _serialize(self, active_chat: Chat) -> Any:
        return active_chat.to_responses_api_chat()

    @staticmethod
    def _provider_safe_tools(req_tools: Any) -> list[Any]:
        """Coerce tools to plain dicts and make their schemas provider-safe.

        DashScope/Bailian ``/responses`` rejects function tools whose
        ``parameters`` lacks the ``required`` key — even a zero-arg
        ``{"type":"object","properties":{}}`` fails the whole response with
        InvalidParameter ("must conform to a valid openai-compatible JSON
        schema"), while OpenAI and llama.cpp accept it. Adding
        ``"required": []`` when missing is a no-op for the model and is
        accepted by all providers.
        """
        tools: list[Any] = []
        for tool in req_tools:
            if hasattr(tool, "model_dump"):
                tool = tool.model_dump(exclude_none=True)
            elif not isinstance(tool, dict):
                try:
                    tool = dict(tool)
                except Exception:
                    tools.append(tool)
                    continue
            params = tool.get("parameters")
            if isinstance(params, dict) and "required" not in params:
                params = dict(params)
                params["required"] = []
                tool = dict(tool)
                tool["parameters"] = params
            tools.append(tool)
        return tools

    def _build_optional_kwargs(self, req_tools: Any, req_tool_choice: Any) -> dict[str, Any]:
        optional_kwargs = self._reasoning_kwargs()
        if req_tools is not None:
            optional_kwargs["tools"] = self._provider_safe_tools(req_tools)
        if req_tool_choice is not None:
            optional_kwargs["tool_choice"] = req_tool_choice
        return optional_kwargs

    def _serialize(self, active_chat: Chat) -> Any:
        return self._provider_safe_input(active_chat.to_responses_api_chat())

    @staticmethod
    def _provider_safe_input(api_input: Any) -> Any:
        """Replace ``function_call_output`` history items with plain user text.

        DashScope/Bailian ``/responses`` internally maps tool outputs to chat
        messages with ``role: "tool"`` and then rejects them ("role: tool must
        be one of user,assistant,system,function" — QwenAgentError 50004),
        failing every request after the first tool call. Keeping the
        structured ``function_call`` item and textifying only the output is
        accepted by OpenAI, llama.cpp and DashScope alike.
        """
        result: list[Any] = []
        for item in api_input:
            itype = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
            if itype == "function_call_output":
                if isinstance(item, dict):
                    call_id = item.get("call_id", "")
                    output = item.get("output", "")
                else:
                    call_id = getattr(item, "call_id", "")
                    output = getattr(item, "output", "")
                result.append(
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": f"[tool result for {call_id}] {output}"}],
                    }
                )
            else:
                result.append(item)
        return result

    def _request(self, api_input: Any, optional_kwargs: dict[str, Any]) -> Any:
        # DEBUG(dashscope): dump request payload for offline inspection; remove once stable
        try:
            import json as _json

            with open("/tmp/last_llm_request.json", "w", encoding="utf-8") as _f:
                _json.dump(
                    {"model": self.model_name, "input": api_input, "kwargs": optional_kwargs, "extra": self._extra_body},
                    _f,
                    ensure_ascii=False,
                    default=str,
                )
        except Exception:
            pass
        return self.client.responses.create(
            model=self.model_name,
            input=api_input,
            stream=self.stream,
            extra_body=self._extra_body,
            timeout=self.request_timeout,
            **optional_kwargs,
        )

    @staticmethod
    def _assistant_content(content: Any) -> list[AssistantContent]:
        return [
            AssistantContent(type="output_text", text=c.text if c.type == "output_text" else c.refusal) for c in content
        ]

    def _iter_stream_events(self, api_response: Stream) -> Iterator[ProviderEvent]:
        saw_terminal = False
        history_item_ids: dict[int, str] = {}
        for raw_event in api_response:
            # DEBUG(dashscope): surface failed/unknown stream events; remove once stable
            _et = getattr(raw_event, "type", None)
            if _et == "response.failed":
                _err = getattr(getattr(raw_event, "response", None), "error", None)
                logger.error("DashScope response.failed: %s", _err)
            elif _et not in {
                "response.created",
                "response.in_progress",
                "response.output_item.added",
                "response.output_item.done",
                "response.content_part.added",
                "response.content_part.done",
                "response.output_text.delta",
                "response.output_text.done",
                "response.output_audio_transcript.delta",
                "response.output_audio_transcript.done",
                "response.completed",
            }:
                logger.info("DashScope stream event: %s", _et)
            if isinstance(raw_event, ResponseTextDeltaEvent):
                yield TextDelta(text=raw_event.delta)
            elif isinstance(raw_event, ResponseOutputItemDoneEvent):
                item = raw_event.item
                if isinstance(item, ResponseFunctionToolCall):
                    if item.status == "incomplete":
                        continue
                    event = self._tool_call(item)
                    assert event.item.id is not None
                    history_item_ids[raw_event.output_index] = event.item.id
                    yield event
                elif isinstance(item, ResponseReasoningItem):
                    history_item_ids[raw_event.output_index] = item.id
                    yield item
                elif isinstance(item, ResponseOutputMessage):
                    message_id = _generate_id("msg")
                    history_item_ids[raw_event.output_index] = message_id
                    yield AssistantMessage(
                        content=self._assistant_content(item.content), id=message_id, response_item=item
                    )
            elif isinstance(raw_event, (ResponseCompletedEvent, ResponseIncompleteEvent, ResponseFailedEvent)):
                saw_terminal = True
                usage = getattr(raw_event.response, "usage", None)
                if usage:
                    yield Usage(input_tokens=usage.input_tokens or 0, output_tokens=usage.output_tokens or 0)
                ending = _response_end(raw_event.response, status=raw_event.type.removeprefix("response."))
                ending.history_item_order = [history_item_ids[index] for index in sorted(history_item_ids)]
                yield ending
            elif isinstance(raw_event, ResponseErrorEvent):
                saw_terminal = True
                yield ProviderResponseEnd(status="failed", error=raw_event.message)
        if not saw_terminal:
            logger.warning("Responses stream ended without a terminal event")
            yield ProviderResponseEnd(
                history_item_order=[history_item_ids[index] for index in sorted(history_item_ids)]
            )

    def _iter_response_events(self, api_response: Any) -> Iterator[ProviderEvent]:
        usage = api_response.usage
        if usage:
            yield Usage(input_tokens=usage.input_tokens or 0, output_tokens=usage.output_tokens or 0)
        yield _response_end(api_response)
        for message in api_response.output:
            if isinstance(message, ResponseFunctionToolCall):
                yield self._tool_call(message)
            elif isinstance(message, ResponseReasoningItem):
                yield message
            elif isinstance(message, ResponseOutputMessage):
                yield AssistantMessage(content=self._assistant_content(message.content), response_item=message)
                # Text-only keeps every character; the base applies remove_unspeechable
                # for audio. Only output_text parts are spoken (refusals are stored).
                raw = "".join(c.text for c in message.content if c.type == "output_text")
                yield TextDelta(text=raw)
            else:
                logger.warning(f"Not supported message type: {message.type}")

    @staticmethod
    def _tool_call(item: ResponseFunctionToolCall) -> ToolCall:
        # Realtime clients keep their existing local identifiers; manual
        # Responses replay uses the untouched provider payload instead.
        return ToolCall(
            item=item.model_copy(update={"id": _generate_id("fc"), "call_id": _generate_id("call")}),
            response_item=item,
        )

    def on_session_end(self) -> None:
        logger.debug("OpenAI API language model session state reset")
