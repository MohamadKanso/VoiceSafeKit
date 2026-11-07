# VoiceSafeKit for the LiteLLM proxy

`VoiceSafeGuardrail` is a LiteLLM custom guardrail. Before a request leaves the proxy it
swaps personal data in the messages for placeholders (`[CARD_1]`, `[EMAIL_1]` ...),
including details spoken as words ("four two four two ..."). When the reply comes back it
puts the real values in again, for normal and streamed Chat Completions.

```bash
pip install "litellm[proxy]" "voicesafekit[litellm] @ git+https://github.com/MohamadKanso/VoiceSafeKit"
export LITELLM_MASTER_KEY=sk-... OPENAI_API_KEY=sk-...
litellm --config examples/litellm/config.yaml
```

```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o-mini", "messages": [{"role": "user",
       "content": "my card is four two four two four two four two four two four two four two four two"}]}'
```

The model receives `my card is [CARD_1]`; your client gets the reply with the real number.
A request whose newest user message is `BLOCK` (a government ID, a card security code, an
emergency) is rejected with HTTP 400 and never reaches the model.

Notes:

- `mode` must include `post_call` for replies to be restored. With `pre_call` only, the
  reply keeps its placeholders.
- Each request gets its own placeholder map, held in memory only between the pre-call and
  post-call hooks. Send the whole conversation each time, as Chat Completions clients do;
  the same history always gets the same numbers.
- Passwords, PINs, CVVs, one-time codes and API keys are redacted but never restored.
- Text completions (`prompt`) and Responses API `input` are redacted too, but only Chat
  Completions replies are restored; other replies keep the placeholders.
