"""Help Agent service package."""

__all__ = ["HelpAgentService", "HelpPlanner"]


def __getattr__(name: str):
    if name == "HelpAgentService":
        from services.help_agent.service import HelpAgentService

        return HelpAgentService
    if name == "HelpPlanner":
        from services.help_agent.planner import HelpPlanner

        return HelpPlanner
    raise AttributeError(name)
