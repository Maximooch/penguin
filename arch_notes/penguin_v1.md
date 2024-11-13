October 17th 2024AD 310p Thursday

God bless us all!

What does Penguin v1 look like?





# refactor into modular cognitive architecture system
Theoretical 



Core/Base

core.py

hub.py?

prompts.py
main.py
config.py
setup.py

  Memory
  - memory search
  - workspace search
  - [x]  context window stuff?
    Something to handle it, cause I noticed once Penguin has the LLM exceed its context window, it just crashes.
  - contextual awareness

Cognition
- reasoning, these can start as simple prompts more or less
- Entropix stuff. 

Processor
- Parser
- Tools
- Utils
- Anything else?

Workspace

System
- Server
- Thought/Message system?
- Conversation handling
- logging
- (later on) Computer Use

Link
- database for tasks (either cloud or local in settings, config/setup must be super easy)
- long enough in the Link app checklist where you can start to look at scalability. Probably going to have to sacrifice a lot on features.   

# various ships needed
  
- [ ]  different types of API support
- language map stuff, or something similar to Aider's repomap system
- not quite sure the relation between Penguin's backend and Link's
- working diagnostics
- [ ]  web search (something free, and perplexity or of the sort)
- [ ]  decent config
- explore dspy? if not, user prompt stuff

- [x] - parser locks!!!! (mostly)
- various cognitive security stuff to prevent jailbreaking

- thought/message system for 24/7 stuff
- cloud hosting? or purely local?


# Fixes

- [ ]  File System
- Awkward UI/UX
- [ ]  it not combining API calls/tool requests together, as old Penguin used to. Making it so much better. (token efficiency must come at the type of API being used, not limiting Penguin's core capability)
- 

# bench, testing, aiming

I don't quite have a good idea how accurate and reliable Penguin v1 would be in terms of the code it generates.


# broader Penguin/Link things

- Properties

- Integration into already existing development environment and tools. 



# possibly later version things

not just general vision capabilities, but a VM where it can interact with software to extend its capability.

Mostly related to Cradle paper.


(Link) products, like entry level customer support
# Business planning (for once)

- this might be speedrunning through some books.


- once I get it hosted on the cloud, and factor in costs of other things, what will its price point be? I'm thinking if I can, about 10-30% markup for profit. If this does work out where I get more than 100 customers, then I don't really need to worry about margins for at least 2 years

                                                       