import os
import asyncio
import time
import logging
from datetime import datetime, timezone

import boto3
import docker
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ALLOWED_ID = int(os.environ["ALLOWED_TELEGRAM_ID"])
AUTO_STOP_MINUTES = int(os.environ.get("AUTO_STOP_MINUTES", 30))
INSTANCE_ID = os.environ.get("INSTANCE_ID", "")

docker_client = docker.DockerClient(base_url="unix:///var/run/docker.sock")
ec2 = boto3.client("ec2")
last_activity = time.time()

CORE_CONTAINERS = ["redis", "postgres", "memory", "orchestrator", "engine"]
DEV_CONTAINER = "devbox"


def check_auth(update: Update) -> bool:
    if update.effective_user.id != ALLOWED_ID:
        update.message.reply_text("Access denied.")
        return False
    return True


def reset_timer():
    global last_activity
    last_activity = time.time()


def get_container(name: str):
    try:
        return docker_client.containers.get(name)
    except docker.errors.NotFound:
        return None


def get_core_status() -> dict[str, str]:
    status = {}
    for name in CORE_CONTAINERS:
        c = get_container(name)
        status[name] = c.status if c else "missing"
    return status


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        return
    reset_timer()
    msg = await update.message.reply_text("Starting dev environment...")
    container = get_container(DEV_CONTAINER)
    if container and container.status == "running":
        await msg.edit_text("Already running.")
        return
    try:
        if container:
            container.start()
        else:
            # Find the network and volumes from existing compose
            networks = [n.name for n in docker_client.networks.list() if "devserver" in n.name.lower()]
            net = networks[0] if networks else "devserver_default"
            docker_client.containers.run(
                "devserver-code-server:latest",
                name=DEV_CONTAINER,
                detach=True,
                ports={"8443/tcp": int(os.environ.get("CODE_SERVER_PORT", 8443))},
                environment={
                    "PUID": "1000", "PGID": "1000",
                    "PASSWORD": os.environ.get("CODE_SERVER_PASSWORD", "stockai"),
                    "DEFAULT_WORKSPACE": "/workspace",
                },
                volumes={
                    "devserver_workspace": {"bind": "/workspace", "mode": "rw"},
                    "devserver_code_server_config": {"bind": "/config", "mode": "rw"},
                    "/opt/stockai": {"bind": "/workspace/StockAI", "mode": "ro"},
                },
                restart_policy={"Name": "no"},
                network=net,
            )
        await msg.edit_text("Started!")
    except Exception as e:
        await msg.edit_text(f"Error: {e}")


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        return
    msg = await update.message.reply_text("Stopping dev environment...")
    container = get_container(DEV_CONTAINER)
    if not container or container.status == "exited":
        await msg.edit_text("Already stopped.")
        return
    try:
        container.stop(timeout=10)
        await msg.edit_text("Stopped.")
    except Exception as e:
        await msg.edit_text(f"Error: {e}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        return
    reset_timer()
    # Dev
    dev = get_container(DEV_CONTAINER)
    dev_state = dev.status if dev else "not created"
    idle = int((time.time() - last_activity) / 60)
    # Core
    core = get_core_status()
    core_line = " ".join(f"{n}={s[:1].upper()}" for n, s in core.items())

    await update.message.reply_text(
        f"Dev: {dev_state} (idle: {idle}min)\n"
        f"App: {core_line}\n"
        f"Auto-stop: {AUTO_STOP_MINUTES}min"
    )


async def cmd_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        return
    reset_timer()
    container = get_container(DEV_CONTAINER)
    if not container or container.status != "running":
        await update.message.reply_text("Dev is not running. Use /start.")
        return
    ip = ec2.describe_instances(InstanceIds=[INSTANCE_ID])["Reservations"][0]["Instances"][0].get("PublicIpAddress", "unknown")
    port = os.environ.get("CODE_SERVER_PORT", "8443")
    pw = os.environ.get("CODE_SERVER_PASSWORD", "stockai")
    await update.message.reply_text(
        f"Code Server: http://{ip}:{port}\n"
        f"Password: {pw}\n\n"
        f"StockAI Dashboard: http://{ip}:8000\n"
        f"Health: http://{ip}:8000/api/v1/health"
    )


async def cmd_exec(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        return
    reset_timer()
    if not context.args:
        await update.message.reply_text("Usage: /exec <command>")
        return
    container = get_container(DEV_CONTAINER)
    if not container or container.status != "running":
        await update.message.reply_text("Dev is not running.")
        return
    cmd = " ".join(context.args)
    msg = await update.message.reply_text(f"Running: {cmd}")
    try:
        result = container.exec_run(cmd, demux=True)
        out = (result.output[0].decode() if result.output[0] else "") + (result.output[1].decode() if result.output[1] else "")
        await msg.edit_text(f"Exit: {result.exit_code}\n\n{out.strip()[:4000]}")
    except Exception as e:
        await msg.edit_text(f"Error: {e}")


async def cmd_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/app start|stop|restart — control StockAI trading services."""
    if not check_auth(update):
        return
    if not context.args or context.args[0] not in ("start", "stop", "restart"):
        await update.message.reply_text("Usage: /app start|stop|restart")
        return
    action = context.args[0]
    msg = await update.message.reply_text(f"App {action}...")
    try:
        import subprocess
        workdir = os.environ.get("COMPOSE_DIR", "/opt/stockai")
        cmd = f"cd {workdir} && docker compose -f docker-compose.yml {action} memory orchestrator engine"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        await msg.edit_text(f"App {action}: exit={result.returncode}\n{result.stdout[:1000]}")
    except Exception as e:
        await msg.edit_text(f"Error: {e}")


async def cmd_setidle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AUTO_STOP_MINUTES
    if not check_auth(update):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /setidle <minutes>")
        return
    AUTO_STOP_MINUTES = int(context.args[0])
    await update.message.reply_text(f"Auto-stop: {AUTO_STOP_MINUTES}min")


async def auto_stop_loop():
    while True:
        await asyncio.sleep(60)
        idle = time.time() - last_activity
        if idle > AUTO_STOP_MINUTES * 60:
            container = get_container(DEV_CONTAINER)
            if container and container.status == "running":
                logger.info(f"Auto-stop after {int(idle/60)}min idle")
                container.stop(timeout=10)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("url", cmd_url))
    app.add_handler(CommandHandler("exec", cmd_exec))
    app.add_handler(CommandHandler("app", cmd_app))
    app.add_handler(CommandHandler("setidle", cmd_setidle))

    # Register command hints in Telegram UI
    async def set_commands():
        await app.bot.set_my_commands([
            BotCommand("start", "Launch VS Code dev environment"),
            BotCommand("stop", "Stop VS Code"),
            BotCommand("status", "Check dev + app status"),
            BotCommand("url", "Get code-server + dashboard URLs"),
            BotCommand("exec", "Run command in code-server"),
            BotCommand("app", "Control StockAI: start/stop/restart"),
            BotCommand("setidle", "Set auto-stop minutes"),
        ])

    loop = asyncio.get_event_loop()
    loop.create_task(auto_stop_loop())
    loop.create_task(set_commands())

    logger.info("DevServer bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
