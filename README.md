<div align="center">
  <img alt="Orion" src="assets/Orion_Horizontal_Logo.png" width="400">

  <p><i>Personal AI, On Personal Devices.</i></p>

  <p>
    <a href="https://scalingintelligence.stanford.edu/blogs/orion/"><img src="https://img.shields.io/badge/project-Orion-blue" alt="Project"></a>
    <a href="https://open-orion.github.io/Orion/"><img src="https://img.shields.io/badge/docs-mkdocs-blue" alt="Docs"></a>
    <img src="https://img.shields.io/badge/python-%3E%3D3.10-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License">
    <a href="https://discord.gg/YZZRxCAhmm"><img src="https://img.shields.io/badge/discord-join-7289da?logo=discord&logoColor=white" alt="Discord"></a>
    <a href="https://x.com/OrionAI"><img src="https://img.shields.io/badge/X-@OrionAI-black?logo=x&logoColor=white" alt="X / Twitter"></a>
  </p>
</div>

---

> **[Documentation](https://open-orion.github.io/Orion/)**
>
> **[Project Site](https://scalingintelligence.stanford.edu/blogs/orion/)**
>
> **[Leaderboard](https://open-orion.github.io/Orion/leaderboard/)**
>
> **[Roadmap](https://open-orion.github.io/Orion/development/roadmap/)**

## Why Orion?

> **⚠️ Important Note on Project Scale & Storage**  
> Orion is a large-scale project designed for advanced on-device AI. To ensure stability and correct behavior, **you must use the given models provided in the configuration**. Please be aware that because these are **local models** designed to run entirely on your own hardware, they require **huge amounts of local storage** and substantial computational resources.

Personal AI agents are exploding in popularity, but nearly all of them still route intelligence through cloud APIs. Your "personal" AI continues to depend on someone else's server. At the same time, our [Intelligence Per Watt](https://www.intelligence-per-watt.ai/) research showed that local language models already handle 88.7% of single-turn chat and reasoning queries, with intelligence efficiency improving 5.3× from 2023 to 2025. The models and hardware are increasingly ready. What has been missing is the software stack to make local-first personal AI practical.

Orion is that stack. It is a framework for local-first personal AI, built around three core ideas: shared primitives for building on-device agents; evaluations that treat energy, FLOPs, latency, and dollar cost as first-class constraints alongside accuracy; and a learning loop that improves models using local trace data. The goal is simple: make it possible to build personal AI agents that run locally by default, calling the cloud only when truly necessary. Orion aims to be both a research platform and a production foundation for local AI, in the spirit of PyTorch.

## Installation

```bash
curl -fsSL https://orion.ai/install.sh | bash
```

That's it. The installer handles everything: uv, the Python venv, Ollama, and pulling a small starter model. About 3 minutes on a typical broadband connection. Then:

```bash
orion
```

The Rust extension and bigger models continue downloading in the background while you chat. Run `orion doctor` to see status.

**Platforms:** macOS (Intel + Apple Silicon), Linux, WSL2 on Windows.

**Manual install / contributors:** see [docs/getting-started/install.md](docs/getting-started/install.md).

## Quick Start

```bash
curl -fsSL https://orion.ai/install.sh | bash
orion
```

`orion init --preset <name>` switches to a starter config. Available presets: `morning-digest-mac`, `morning-digest-linux`, `morning-digest-minimal`, `deep-research`, `code-assistant`, `scheduled-monitor`, `chat-simple`.

## Starter Configs

Install any preset with one command:

```bash
uv run orion init --preset morning-digest-mac   # or any preset below
```

> Prefix every `orion ...` invocation with `uv run`, or activate the venv first (`source .venv/bin/activate`) so plain `orion ...` works for the rest of your shell session.

| Preset | Use Case | What it does |
|--------|----------|-------------|
| `morning-digest-mac` | Daily Briefing (Mac) | Spoken briefing from email, calendar, health, news with Orion voice |
| `morning-digest-linux` | Daily Briefing (Linux) | Same, with vLLM support for GPU servers |
| `morning-digest-minimal` | Daily Briefing (minimal) | Just Gmail + Calendar, runs on any machine |
| `deep-research` | Research Assistant | Multi-hop research across indexed docs with citations |
| `code-assistant` | Code Companion | Agent with code execution, file I/O, and shell access |
| `scheduled-monitor` | Persistent Monitor | Stateful agent that runs on a schedule with memory |
| `chat-simple` | Simple Chat | Lightweight conversation, no tools needed |

```bash
# Example: Morning Digest on Mac
uv run orion init --preset morning-digest-mac
uv run orion connect gdrive          # one OAuth flow covers Gmail, Calendar, Tasks
uv run orion digest --fresh          # generate and play your first briefing

# Example: Deep Research
uv run orion init --preset deep-research
uv run orion memory index ./docs/    # requires the Rust extension — see Setup above
uv run orion ask "Summarize all emails about Project X"
```

### Skills

Skills teach agents how to better use tools and improve their reasoning. Every skill is a tool — agents discover them from a catalog and invoke them on demand.

```bash
# Install skills from public sources
orion skill install hermes:arxiv
orion skill sync hermes --category research

# Use skills with any agent
orion ask "Use the code-explainer skill to explain this Python code: for i in range(5): print(i*2)"

# Optimize skills from your trace history
orion optimize skills --policy dspy

# Benchmark the impact
orion bench skills --max-samples 5 --seeds 42
```

Import from [Hermes Agent](https://github.com/NousResearch/hermes-agent) (~150 skills), [OpenClaw](https://github.com/openclaw/skills) (~13,700 community skills), or any GitHub repo. Skills follow the [agentskills.io](https://agentskills.io/specification) open standard.

See the [Skills User Guide](https://open-orion.github.io/Orion/user-guide/skills/) and [Skills Tutorial](https://open-orion.github.io/Orion/tutorials/skills-workflow/) for details.

### Built-in Agents

Orion ships with eight built-in agents across three execution modes (on-demand, scheduled, continuous):

| Agent | Type | What it does |
|-------|------|-------------|
| `morning_digest` | Scheduled | Daily briefing from email, calendar, health, news — with TTS audio |
| `deep_research` | On-demand | Multi-hop research with citations across web and local docs |
| `monitor_operative` | Continuous | Long-horizon monitoring with memory, compression, and retrieval |
| `orchestrator` | On-demand | Multi-turn reasoning with automatic tool selection |
| `native_react` | On-demand | ReAct (Thought-Action-Observation) loop agent |
| `operative` | Continuous | Persistent autonomous agent with state management |
| `native_openhands` | On-demand | CodeAct — generates and executes Python code |
| `simple` | On-demand | Single-turn chat, no tools |

See the [User Guide](https://open-orion.github.io/Orion/user-guide/morning-digest/) and [Tutorials](https://open-orion.github.io/Orion/tutorials/) for detailed setup instructions.

Full documentation — including Docker deployment, cloud engines, development setup, and tutorials — at **[open-orion.github.io/Orion](https://open-orion.github.io/Orion/)**.

## Community

- **GitHub:** [github.com/open-orion/Orion](https://github.com/open-orion/Orion)
- **Discord:** [discord.gg/YZZRxCAhmm](https://discord.gg/YZZRxCAhmm)
- **X / Twitter:** [@OrionAI](https://x.com/OrionAI)
- **Docs:** [open-orion.github.io/Orion](https://open-orion.github.io/Orion/)

## Contributing

We welcome contributions! See the [Contributing Guide](CONTRIBUTING.md) for incentives, contribution types, and the PR process.

Quick start for contributors:

```bash
git clone https://github.com/open-orion/Orion.git
cd Orion
uv sync --extra dev
uv run pre-commit install
uv run pytest tests/ -v
```

Browse the [Roadmap](https://open-orion.github.io/Orion/development/roadmap/) for areas where help is needed. Comment **"take"** on any issue to get auto-assigned.

## About

Orion is part of [Intelligence Per Watt](https://www.intelligence-per-watt.ai/), a research initiative studying the intelligence efficiency of AI systems. The project is developed at [Hazy Research](https://hazyresearch.stanford.edu/) and the [Scaling Intelligence Lab](https://scalingintelligence.stanford.edu/) at [Stanford SAIL](https://ai.stanford.edu/).

## Sponsors

<p>
  <a href="https://www.laude.org/">Laude Institute</a> &bull;
  <a href="https://datascience.stanford.edu/marlowe">Stanford Marlowe</a> &bull;
  <a href="https://cloud.google.com/">Google Cloud Platform</a> &bull;
  <a href="https://lambda.ai/">Lambda Labs</a> &bull;
  <a href="https://ollama.com/">Ollama</a> &bull;
  <a href="https://research.ibm.com/">IBM Research</a> &bull;
  <a href="https://hai.stanford.edu/">Stanford HAI</a>
</p>

## Citation
```bibtex
@misc{saadfalcon2026orionpersonalaipersonal,
      title={Orion: Personal AI, On Personal Devices}, 
      author={Jon Saad-Falcon and Avanika Narayan and Robby Manihani and Tanvir Bhathal and Herumb Shandilya and Hakki Orhun Akengin and Gabriel Bo and Andrew Park and Matthew Hart and Caia Costello and Chuan Li and Christopher Ré and Azalia Mirhoseini},
      year={2026},
      eprint={2605.17172},
      archivePrefix={arXiv},
      primaryClass={cs.LG},
      url={https://arxiv.org/abs/2605.17172}, 
}
```

## License

[Apache 2.0](LICENSE)
