# Python Pull Text Agent

Set `WORKWORLD_API_URL` and `WORKWORLD_AGENT_CREDENTIAL`, then run `python agent.py` with the
Python SDK installed. By default this example uses a deterministic local summarizer and labels
that mode in its progress event. To opt into a real hosted summarizer, set `OPENAI_API_KEY` and
optionally `OPENAI_MODEL` (default `gpt-5-mini`); hosted failures fail the Run and never fall back
to deterministic output.
