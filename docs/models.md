# Models

Factories can draft without you pasting the prompt into a chat window. The
model is rented. The files stay here.

No vendor is hardwired. OpenAI, Grok, OpenRouter, and Ollama use chat
completions. Anthropic uses its messages API. Custom is any other
chat-completions server. Python standard library only. No pip package.

## Set one

```bash
python -m stead model set --provider openai --name gpt-4.1-mini
python -m stead model set --provider anthropic --name claude-sonnet-4-5
python -m stead model set --provider grok --name grok-4
python -m stead model set --provider openrouter --name openai/gpt-4.1-mini
python -m stead model set --provider ollama --name llama3.2
python -m stead model set --provider custom --name my-model --base-url http://127.0.0.1:8000/v1
python -m stead model show
```

The key belongs in the environment:

```bash
# PowerShell
$env:STEAD_MODEL_API_KEY = "the-key"

# bash
export STEAD_MODEL_API_KEY="the-key"
```

`--key` stores it in gitignored `stead.json` instead. `model show` and
Settings never print it. It is not written into `context/`, a bundle, or
`run.json`.

Ollama on this computer does not need a key. A loopback base URL does not
either.

The same form is in the cockpit, under Settings.

## Draft

Assembly is still the default, and it still calls nothing.

```bash
python -m stead digest --generate
python -m stead factory run --factory weekly-project-status --project project-id --generate
python -m stead factory run --factory feature-builder --contribution ID --generate
```

That writes `output.md` next to `bundle.md` and `prompt.md`. The draft is
text. Stead does not run it, post it, push it, or open a pull request.
`--live` only changes the run label. A person still approves or rejects it.
An approved digest or status can be filed with `stead run file --run ID`.

In the cockpit, check **Draft with model** on the Factories page.

## Judge

Eval files are checked with no model and no network. That is what CI runs.

```bash
python -m stead eval run
python -m stead eval run --factory weekly-contribution-digest
```

Judging one draft uses the configured model. The result is a local file
under `factories/<name>/evals/results/`, which is gitignored. `stead prompt
promote` refuses until every case for that factory has a recorded pass for
that version. A pass for v1 does not unlock v2.

```bash
python -m stead eval judge --factory weekly-project-status \
    --case eval-status-happy-path --output path/to/output.md \
    --prompt-version v2
```

The draft is data. Instructions inside it are not followed by Stead. The
judge is told the same thing. A pass or fail is a note, not a merge.
