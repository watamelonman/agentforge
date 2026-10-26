"""agentforge: the code behind bin/forge, split by responsibility.

The package namespace re-exports every public name, so `from agentforge import *` (what
bin/forge does) and the tests' `forge.<name>` lookups keep working. Module map:
docs/ARCHITECTURE.md. To patch a module-level setting such as pools.POOL_DIR, set it on
the module that owns it (`agentforge.pools.POOL_DIR = ...`), not on this namespace.
"""
from .util import *            # noqa: F401,F403  paths, sh/git/die, glob_match, small helpers
from .project import *         # noqa: F401,F403  Project, ConfigView, locks
from .cards import *           # noqa: F401,F403  task card loading/writing
from .vendors import *         # noqa: F401,F403  vendor registry, family/harness lookup
from .glm import *             # noqa: F401,F403  Z.ai key + env for glm
from .pools import *           # noqa: F401,F403  cross-project plan pools
from .resettime import *       # noqa: F401,F403  "resets at ..." parsing
from .limits import *          # noqa: F401,F403  cooldowns, allowances, spend
from .parsers import *         # noqa: F401,F403
from .parsers.claude import *  # noqa: F401,F403
from .parsers.codex import *   # noqa: F401,F403
from .parsers.opencode import *  # noqa: F401,F403
from .parsers.grok import *    # noqa: F401,F403
from .parsers.jsonblob import *  # noqa: F401,F403
from .detect import *          # noqa: F401,F403  limit/auth detection in agent output
from .harness import *         # noqa: F401,F403
from .harness.claude import *  # noqa: F401,F403
from .harness.codex import *   # noqa: F401,F403
from .harness.grok import *    # noqa: F401,F403
from .harness.sandbox import *  # noqa: F401,F403
from .harness.opencode import *  # noqa: F401,F403
from .process import *         # noqa: F401,F403  supervised subprocess
from .runner import *          # noqa: F401,F403  run_agent
from .gates import *           # noqa: F401,F403
from .gates.diff import *      # noqa: F401,F403
from .gates.policy import *    # noqa: F401,F403
from .gates.doccheck import *  # noqa: F401,F403
from .gates.layers import *    # noqa: F401,F403
from .choice import *          # noqa: F401,F403  worker/reviewer choice
from .gitops import *          # noqa: F401,F403
from .context import *         # noqa: F401,F403  context pack
from .task import *            # noqa: F401,F403  run_task
from .policy_lists import *    # noqa: F401,F403
from .commands.setup import *  # noqa: F401,F403
from .commands.agents import *  # noqa: F401,F403
from .commands.info import *   # noqa: F401,F403
from .scheduler import *       # noqa: F401,F403  forge run
from .doctor import *          # noqa: F401,F403
from .cli import *             # noqa: F401,F403
