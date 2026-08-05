# systemd Service (Linux)

Orion includes a systemd unit file for running the API server as a managed background service on Linux. This provides automatic startup on boot, crash recovery, and integration with standard Linux service management tools.

## Prerequisites

Before installing the service, ensure that:

1. Orion is installed in a virtual environment at `/opt/orion/.venv` (or adjust paths accordingly).
2. A dedicated `orion` system user exists (recommended for security).
3. An inference engine (such as Ollama) is running and accessible.

Create the user and installation directory:

```bash
sudo useradd --system --create-home --home-dir /opt/orion orion
sudo -u orion python3 -m venv /opt/orion/.venv
sudo -u orion git clone https://github.com/open-orion/Orion.git /opt/orion/Orion
cd /opt/orion/Orion && sudo -u orion uv sync --extra server
```

## Installing the Service

Copy the unit file to the systemd directory, reload the daemon, and enable the service:

```bash
sudo cp deploy/systemd/orion.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable orion
sudo systemctl start orion
```

Verify it is running:

```bash
sudo systemctl status orion
```

## Service File Reference

The provided unit file at `deploy/systemd/orion.service`:

```ini
[Unit]
Description=Orion API Server
After=network.target

[Service]
Type=simple
User=orion
WorkingDirectory=/opt/orion
ExecStart=/opt/orion/.venv/bin/orion serve --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
Environment=HOME=/opt/orion

[Install]
WantedBy=multi-user.target
```

### `[Unit]` Section

| Directive     | Value              | Description                                                                 |
|---------------|--------------------|-----------------------------------------------------------------------------|
| `Description` | `Orion API Server` | Human-readable name shown in `systemctl status` and logs.              |
| `After`       | `network.target`   | Delays startup until the network stack is available, since the server binds to a network socket and may need to reach a remote engine. |

### `[Service]` Section

| Directive          | Value                                                              | Description                                                                                     |
|--------------------|--------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| `Type`             | `simple`                                                           | The process started by `ExecStart` is the main service process. systemd considers the service started immediately. |
| `User`             | `orion`                                                       | Runs the server as the `orion` user rather than root, limiting the blast radius of any security issue. |
| `WorkingDirectory` | `/opt/orion`                                                  | Sets the working directory for the process. This is where Orion looks for local files and writes data. |
| `ExecStart`        | `/opt/orion/.venv/bin/orion serve --host 0.0.0.0 --port 8000` | The command to start the server. Uses the full path to the `orion` binary inside the virtual environment. |
| `Restart`          | `on-failure`                                                       | Automatically restarts the service if it exits with a non-zero exit code. Does not restart on clean shutdown (`systemctl stop`). |
| `RestartSec`       | `5`                                                                | Waits 5 seconds before attempting a restart, preventing rapid restart loops if the service crashes immediately on startup. |
| `Environment`      | `HOME=/opt/orion`                                             | Sets the `HOME` environment variable so Orion finds its configuration at `~/.orion/config.toml` (resolving to `/opt/orion/.orion/config.toml`). |

### `[Install]` Section

| Directive    | Value               | Description                                                                                 |
|--------------|---------------------|---------------------------------------------------------------------------------------------|
| `WantedBy`   | `multi-user.target` | The service starts when the system reaches multi-user mode (standard boot target for servers). `systemctl enable` creates a symlink under this target. |

## Configuration Options

### Changing the Bind Address and Port

Edit the `ExecStart` line to change the host or port:

```ini
ExecStart=/opt/orion/.venv/bin/orion serve --host 127.0.0.1 --port 9000
```

!!! tip
    Binding to `127.0.0.1` restricts access to localhost only. Use this when running behind a reverse proxy like Nginx or Caddy.

### Setting the Engine and Model

Pass additional flags to `orion serve`:

```ini
ExecStart=/opt/orion/.venv/bin/orion serve --host 0.0.0.0 --port 8000 --engine ollama --model qwen3:8b
```

### Adding Environment Variables

Add multiple `Environment` directives or use `EnvironmentFile` for complex configurations:

```ini
[Service]
Environment=HOME=/opt/orion
Environment=OPENORION_ENGINE_DEFAULT=vllm
Environment=OPENORION_OLLAMA_HOST=http://localhost:11434
```

Or load from a file:

```ini
[Service]
EnvironmentFile=/opt/orion/.env
```

### Changing the User

If you prefer a different service user, update both the `User` directive and the paths:

```ini
[Service]
User=myuser
WorkingDirectory=/home/myuser/orion
ExecStart=/home/myuser/orion/.venv/bin/orion serve --host 0.0.0.0 --port 8000
Environment=HOME=/home/myuser/orion
```

### Using a Configuration File

Ensure the configuration file exists at the path where `HOME` points:

```bash
sudo -u orion mkdir -p /opt/orion/.orion
sudo -u orion cp config.toml /opt/orion/.orion/config.toml
```

The server reads `~/.orion/config.toml` on startup, where `~` resolves from the `HOME` environment variable.

## Viewing Logs

Orion logs are captured by journald. View them with `journalctl`:

```bash
# View all logs for the service
sudo journalctl -u orion

# Follow logs in real time
sudo journalctl -u orion -f

# View logs since the last boot
sudo journalctl -u orion -b

# View logs from the last hour
sudo journalctl -u orion --since "1 hour ago"

# View only error-level messages
sudo journalctl -u orion -p err
```

## Managing the Service

### Start, Stop, and Restart

```bash
# Start the service
sudo systemctl start orion

# Stop the service
sudo systemctl stop orion

# Restart the service (stop + start)
sudo systemctl restart orion

# Reload configuration without full restart (sends SIGHUP)
sudo systemctl reload-or-restart orion
```

### Check Status

```bash
sudo systemctl status orion
```

Example output:

```
● orion.service - Orion API Server
     Loaded: loaded (/etc/systemd/system/orion.service; enabled; preset: enabled)
     Active: active (running) since Fri 2026-02-21 10:00:00 UTC; 2h ago
   Main PID: 12345 (orion)
      Tasks: 4 (limit: 4915)
     Memory: 256.0M
        CPU: 1min 23s
     CGroup: /system.slice/orion.service
             └─12345 /opt/orion/.venv/bin/python /opt/orion/.venv/bin/orion serve --host 0.0.0.0 --port 8000
```

### Enable and Disable on Boot

```bash
# Enable automatic start on boot
sudo systemctl enable orion

# Disable automatic start on boot
sudo systemctl disable orion
```

### Apply Changes After Editing the Unit File

After modifying `/etc/systemd/system/orion.service`, reload the systemd daemon and restart the service:

```bash
sudo systemctl daemon-reload
sudo systemctl restart orion
```

## Running Alongside Ollama

If Ollama is also managed via systemd, you can add an ordering dependency so the Orion service waits for Ollama to start:

```ini
[Unit]
Description=Orion API Server
After=network.target ollama.service
Requires=ollama.service
```

| Directive  | Description                                                              |
|------------|--------------------------------------------------------------------------|
| `After`    | Ensures Orion starts after Ollama.                                  |
| `Requires` | If Ollama fails to start, Orion will not start either.              |

!!! note
    Use `Wants` instead of `Requires` if you want Orion to start even when Ollama is unavailable (for example, if you plan to start Ollama manually later).
