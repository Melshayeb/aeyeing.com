#!/usr/bin/env python3
"""Lightweight kill-switch guard.

main.py can import this to check whether it should run a component.
Kill switches in config.yaml override per-component enabled flags.
"""
import os
import yaml
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Default paths and keys
CONFIG_PATH = Path.home() / ".hermes" / "skills" / "ozmoeg-money-maker" / "config.yaml"
KILL_SWITCH_KEY = "kill_switch_enabled"
KILL_SWITCH_SECTION = "kill_switch"

VALID_SWITCHES = [
    "master", "scanner", "news", "strategy",
    "telegram_alerts", "email_alerts", "website_updates", "okx_sentiment",
]

# Global config cache
_cached_config = None

def _load_config() -> dict:
    """Load config from file or return empty dict if missing."""
    global _cached_config
    if _cached_config is not None:
        return _cached_config
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                _cached_config = yaml.safe_load(f) or {}
        else:
            _cached_config = {}
    except Exception as e:
        logger.warning("Failed to load config: %s", e)
        _cached_config = {}
    return _cached_config


def load_config(path: str = None) -> dict:
    """Load and return the entire config.
    
    Optional parameter path is ignored for now (could be used for testing).
    """
    return _load_config()


def is_enabled(config: dict, component: str = None) -> bool:
    """Check if a component is enabled via kill-switch or manual flag.
    
    The component is enabled if:
      - The master kill switch allows it
      - There is no component-specific kill switch
      - The component's enabled flag is true
    """
    if not config:
        config = _load_config()
    
    # Master kill switch overrides everything
    if config.get(KILL_SWITCH_SECTION, {}).get(KILL_SWITCH_KEY, False):
        logger.info("Master kill switch overrides: disabling all components")
        return False
    
    # Component-specific kill switch (legacy behavior: disable key means OFF)
    ks = config.get("kill_switches", {})
    if component and component in ks:
        if not ks[component]:
            logger.info("Component '%s' disabled via kill switch", component)
            return False
    
    # Component-specific enabled flag (new behavior)
    if component:
        component_section = config.get("components", {}).get(component, {})
        if component_section.get("disable", False):
            logger.info("Component '%s' disabled via kill switch", component)
            return False
        if not component_section.get("enabled", True):
            logger.info("Component '%s' disabled via enabled flag", component)
            return False
    
    logger.info("Component '%s' enabled via flag", component)
    return True


def component_enabled(config: dict, component: str, default: bool = True) -> bool:
    """Simplify checking component status with explicit default."""
    return is_enabled(config, component)


def show_kill_status(config: dict):
    """Print current kill-switch status."""
    master = config.get(KILL_SWITCH_SECTION, {}).get(KILL_SWITCH_KEY, False)
    enabled = config.get("components", {})
    ks = config.get("kill_switches", {})
    print("Kill-Switch Status:")
    print(f"  Master kill switch: {'ENABLED' if master else 'DISABLED'}")
    for comp, cfg in enabled.items():
        state = "ENABLED" if cfg.get("enabled", False) else "DISABLED"
        print(f"  Component '{comp}': {state}")
    for comp in VALID_SWITCHES:
        if comp not in enabled:
            state = "ENABLED" if ks.get(comp, True) else "DISABLED"
            print(f"  Legacy kill switch '{comp}': {state}")
    print("  Components can be enabled/disabled via config under components.*enabled")