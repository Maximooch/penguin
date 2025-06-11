# Checkpointing and Branching

Penguin supports saving conversation checkpoints so you can easily return to a previous state or explore alternate approaches on a new branch.

## Creating Checkpoints

- **Automatic**: Penguin can create checkpoints every few messages. Configure the interval in your `.penguin/config.yaml`.
- **Manual**: Use `/checkpoint` in chat or `penguin checkpoint` on the CLI to save the current state.

## Listing Checkpoints

- `/checkpoints` or `penguin checkpoints` shows recent checkpoints.
- Each checkpoint is referenced by the message ID at which it was created.

## Branching and Rollback

- `/branch <msg_id>` or `penguin branch <msg_id>` forks a new conversation starting from that checkpoint.
- `/rollback <msg_id>` or `penguin rollback <msg_id>` rewinds the main thread to an earlier checkpoint.
- View the conversation tree with `/tree` or `penguin tree` to see all branches.

## Configuration Tips

Adjust checkpoint frequency and retention in the configuration file. You can also choose which data to capture (conversation, tasks, or code) for each checkpoint.

For design mockups of the checkpoint UI, see [UI Mockups](../../misc/UI_mockups_checkpointing.md).
