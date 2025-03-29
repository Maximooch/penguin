March 28th 2025AD Friday 1248p:

God bless us all! 

4 Principles:

1. Context
2. Open Endedness
3. Coherence
4. Accessibility 


The conversation/state refactor was mostly successful. Now let's move onto 4 different plans:

1. Messaging System
2. Task/Run System
3. Processor System
4. Prompting, Context, and Orthodox operations
5. Memory Systems 
6. Link and Interfaces (or Penguin Web interface)
7. Hosting and Deployment
8. Company building 

356p

# Messaging 

The main change is to allow for clarification requests

Message interuption should be a thing which doesn't break the state. A user may ask a question while a Penguin is working on something else. 

Then it's to make the inner loop more seamless. There will be no set limit. But **there may be interuptions**

Similar to the current multi-step system, a message could be made of multiple messages 

Next thing is probably for communication to have different states like "Chat" and "Work". 

    You may ask a Penguin a question while it's working, kind of like how a Human would, they would pause what they're currently working on to respond to you. 
    
    Likewise with the clarification thing, I supppose it could outright pause Penguin operations, or it could just continue working on something else until you get a response. (risk of rewarad hacking)

File upload is another thing obviously. I need some general purpose pipeline from multiple providers. 

Queueing messages? 

Ensure streaming works, and fits well within the new CLI. As well as web interface. 

0. Empty Responses issue. Coming from even the native Anthropic adapter, so it's 100% something in Penguin.
1. Interruptions 
2. User clarification/confirmations
3. File Uploads
4. Queueing messages


# Task/Run/Continuous System

- require verification/approval to ensure tasks are actually complete. 
- could just be a dashboard seperate, for the user to see real time. 



- require verification/approval to ensure tasks are actually complete. 


# Prompting/Context/Orthodox operations

- I'd like to mix between regular, deep thoughtful thinking, and chain of draft. 

My prompting approach mostly for coding is for Penguin to approach it through scaffolding.

- Penguin writes into context folder, memory bank of sorts
- there is a config file for the most necessary context files that are loaded every session
- context files can be edited by the user and penguin. 

1. Change System Prompt
2. Change Prompt Workflow
3. In the Prompt Actions, have a coding practices section. Or maybe that could be its own prompt

# Processor System

Main thing is diffs, and working with version control. 

Are they able to view commits, including the code changes

1. 


# Link and other interfaces 

I'll include information about the workspace here. 

So for a start, I think Users should control the data Penguins have access to. Later on as Link matures we'll start having more and more on a cloud workspace people can use, but for now we'll assume people will be using their already existing workspaces. 

- Real Time Chat Application
- Project Management 
- File Server (mostly for Penguins)
- Integrations

# Hosting and deployment


# Timelines

I believe I can wrap these up by April 1st. I'll start planning and try to write the necessary things for the messaging system today, Friday (though I may need to stay up). 

Saturday will be the task system (which interconnects with the messaging system). If I can also do the Orthodox operations stuff, that'd be great. 

But the bigger issue is I'm reasoning by analogy and not first principles, so I don't actually know what I'm planning for. How can I break out of the bottleneck? What is just barely past the limit of impossible. 