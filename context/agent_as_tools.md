September 22nd 2025AD 1002p Monday

God bless us all! 


Sub-agents and Lite agents need to be tools that the parent Penguin agents can use. Most of the backend is stable enough where this can be done. Although there will be additional testing to be sure. 

The lite agents will be particular tools. Similar to how Claude Code does theirs. Like read-file, search web, etc. These are *expected* to only be single turn.

Sub-Agents are slightly more autonomous and more long running. Although assumed to not be as long running as parent agents. (No such thing as a child agent transfer from one parent agent to another, yet, nor there may be any time soon?)



<spawn_sub_agent>It's assumed here will be the outline of a task: as well params for what tools it'll have permission to? </spawn_sub_agent>

<stop_sub_agent> This will stop. They can be resumed. 

There won't be any destory, mostly because in terms of checkpointing it's not really practical. At least now.


<delegate> can be for existing agents. 

if we have roles there could be <send_to_role>

It'll be using the existing MessageBus and all other infra for multi-agent/human communication.

There is an open question about integration with project management, but for the sake of simplicity and robustness, it's probably better not for now. The delegation the parent agent will do should be enough for now.