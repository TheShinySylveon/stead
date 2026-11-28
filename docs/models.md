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

The same form is in the cockpit, under Settings (including optional `--input-price`, `--output-price`, `--call-timeout`, `--context`, and `--key-env`).

## Multiple profiles & role bindings

Save named provider connections and bind them to individual jobs (`build`,
`draft`, `review`, `address`, `judge`):

```bash
python -m stead model add local --provider ollama --name qwen3:30b --context 32768
python -m stead model add strong --provider openai --name gpt-4.1 --key-env OPENAI_API_KEY --input-price 2.0 --output-price 8.0
python -m stead model role draft strong
python -m stead model role review strong
python -m stead model role build local
python -m stead model role judge strong
python -m stead model profiles
python -m stead model role review -   # unbind (falls back to default model)
python -m stead model remove local
```

Settings → **Model profiles** exposes the same profile management and role
bindings. The `judge` role is used only for factory evals. Clear the binding
(or run `python -m stead model role judge -`) to use the active build model,
including a bound build profile. Eval results record the model that judged
the draft.

## Verify it works

`model test` makes one live call and reports latency and the reply. It never
prints the key. `model list` asks the endpoint which model ids it offers.

```bash
python -m stead model test
python -m stead model list
```

Settings has **Test connection** and **List models** buttons that do the same.

For local-first use, Ollama keeps every prompt on this computer and needs no
key. If it is not installed:

```bash
winget install Ollama.Ollama      # then start Ollama
ollama pull llama3.2              # or a smaller model, e.g. qwen2.5:3b
python -m stead model set --provider ollama --name llama3.2
python -m stead model test
```

A build, a review, `spec draft`, and `eval judge` give each model call 300 seconds. A large local model can need more,
because every call resends the files it has read so far; a 27B model
reading a 1,400-line file can run past five minutes in one call. Raise the
limit per model (30 to 7200 seconds); `model show` prints it:

```bash
python -m stead model set --provider custom --name my-27b --base-url http://127.0.0.1:1234/v1 --call-timeout 1200
```

A timeout stops the build with a recorded failure and uses the spec's one
attempt, so re-run with `--retry` after raising the limit.

A hosted provider needs a key and sends prompts to that provider; see
[Trust](trust.md) for exactly what leaves the machine.

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

`stead build` uses the same configured model as an implementation agent: it
plans first, then edits files in the repo's `code_path`, runs the repo's
`checks:` command, and commits locally. `--publish` opens the pull request.

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
