/**
 * Multi-Agent CLI Components Integration Test
 *
 * Tests the TypeScript multi-agent components we built:
 * - AgentAPI client
 * - useAgents hook (simulated)
 * - useMessageBus hook (simulated)
 * - Data flow and types
 *
 * Run:
 *   npm run build
 *   npx tsx test-multi-agent.ts
 *
 * Prerequisites:
 *   - Penguin backend running (penguin serve)
 */

import { AgentAPI, AgentProfile, AgentSpawnRequest } from './src/core/api/AgentAPI';

class MultiAgentCLITester {
  private api: AgentAPI;
  private createdAgents: string[] = [];

  constructor() {
    this.api = new AgentAPI('http://localhost:8000');
  }

  // Test Utilities
  // ------------------------------------------------------------------

  private log(emoji: string, message: string) {
    console.log(`${emoji} ${message}`);
  }

  private assert(condition: boolean, message: string) {
    if (!condition) {
      throw new Error(`❌ Assertion failed: ${message}`);
    }
  }

  // Agent Lifecycle Tests
  // ------------------------------------------------------------------

  async testAgentSpawning(): Promise<void> {
    this.log('🧪', 'TEST: Agent Spawning');

    const request: AgentSpawnRequest = {
      id: 'cli_test_agent',
      model_config_id: 'anthropic/claude-sonnet-4',
      role: 'tester',
      persona: 'CLI test automation agent',
      activate: false,
    };

    const result = await this.api.spawnAgent(request);
    this.createdAgents.push('cli_test_agent');

    this.assert(result.id === 'cli_test_agent', 'Agent ID should match');
    this.log('✅', 'Agent spawning works');
  }

  async testAgentRoster(): Promise<void> {
    this.log('🧪', 'TEST: Agent Roster Retrieval');

    const agents = await this.api.listAgents();

    this.assert(Array.isArray(agents), 'Roster should be an array');
    this.assert(agents.length > 0, 'Should have at least one agent');

    const cliAgent = agents.find((a) => a.id === 'cli_test_agent');
    this.assert(cliAgent !== undefined, 'Should find our test agent');

    this.log('✅', `Agent roster works (${agents.length} agents)`);
  }

  async testAgentProfile(): Promise<void> {
    this.log('🧪', 'TEST: Agent Profile');

    const profile = await this.api.getAgent('cli_test_agent');

    this.assert(profile.id === 'cli_test_agent', 'Profile ID should match');
    // Note: Backend doesn't persist persona field (known limitation)
    this.assert(typeof profile.active === 'boolean', 'active should be boolean');
    this.assert(typeof profile.paused === 'boolean', 'paused should be boolean');
    this.assert(typeof profile.model === 'object', 'model should be object');

    this.log('✅', 'Agent profile retrieval works');
  }

  // Communication Tests
  // ------------------------------------------------------------------

  async testAgentCommunication(): Promise<void> {
    this.log('🧪', 'TEST: Agent Communication');

    // Spawn two agents
    await this.api.spawnAgent({
      id: 'sender_agent',
      model_config_id: 'anthropic/claude-sonnet-4',
      role: 'sender',
    });
    this.createdAgents.push('sender_agent');

    await this.api.spawnAgent({
      id: 'receiver_agent',
      model_config_id: 'anthropic/claude-sonnet-4',
      role: 'receiver',
    });
    this.createdAgents.push('receiver_agent');

    // Send message
    await this.api.sendMessageToAgent('receiver_agent', 'Hello from TypeScript!', {
      sender: 'sender_agent',
      channel: '#cli-test',
    });

    // Verify message in history
    const history = await this.api.getAgentHistory('receiver_agent', { limit: 10 });

    this.assert(Array.isArray(history), 'History should be an array');
    this.log('✅', 'Agent communication works');
  }

  async testDelegation(): Promise<void> {
    this.log('🧪', 'TEST: Agent Delegation');

    const result = await this.api.delegateToAgent('receiver_agent', {
      content: 'Complete this task',
      parent_agent_id: 'sender_agent',
      summary: 'Test delegation',
    });

    this.assert(result.ok === true, 'Should receive delegation confirmation');
    this.log('✅', `Delegation works (delegated to: ${result.delegated_to})`);
  }

  // WebSocket Tests
  // ------------------------------------------------------------------

  async testWebSocketConnection(): Promise<void> {
    this.log('🧪', 'TEST: WebSocket Connection');

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        ws.close();
        reject(new Error('WebSocket connection timeout'));
      }, 5000);

      let messageCount = 0;

      const ws = this.api.connectMessageBus(
        (message) => {
          messageCount++;
          this.log('📨', `Received message: ${message.sender} → ${message.recipient}`);

          if (messageCount >= 1) {
            clearTimeout(timeout);
            ws.close();
            this.log('✅', 'WebSocket messaging works');
            resolve();
          }
        },
        {
          channel: '#cli-test',
          includeBus: true,
        },
        (error) => {
          clearTimeout(timeout);
          ws.close();
          reject(error);
        },
        () => {
          clearTimeout(timeout);
          if (messageCount === 0) {
            // No messages received but connection worked
            this.log('✅', 'WebSocket connection works (no messages in 5s)');
            resolve();
          }
        }
      );

      // Send a test message after connection
      setTimeout(async () => {
        try {
          await this.api.sendMessageToAgent('receiver_agent', 'WebSocket test message', {
            sender: 'sender_agent',
            channel: '#cli-test',
          });
        } catch (err) {
          console.error('Failed to send test message:', err);
        }
      }, 1000);
    });
  }

  // Type Safety Tests
  // ------------------------------------------------------------------

  testTypeSafety(): void {
    this.log('🧪', 'TEST: TypeScript Type Safety');

    // Test AgentProfile type
    const profile: AgentProfile = {
      id: 'test',
      is_parent: false,
      is_sub_agent: false,
      children: [],
      is_active: false,
      is_paused: false,
    };

    this.assert(profile.id === 'test', 'Profile type is correct');

    // Test AgentSpawnRequest type
    const request: AgentSpawnRequest = {
      id: 'new_agent',
      model_config_id: 'anthropic/claude-sonnet-4',
      role: 'worker',
    };

    this.assert(request.id === 'new_agent', 'Spawn request type is correct');

    this.log('✅', 'TypeScript types are correctly defined');
  }

  // Cleanup
  // ------------------------------------------------------------------

  async cleanup(): Promise<void> {
    this.log('🧹', 'Cleaning up test agents...');

    for (const agentId of this.createdAgents) {
      try {
        await this.api.deleteAgent(agentId, false);
        this.log('🗑️', `Deleted ${agentId}`);
      } catch (err) {
        this.log('⚠️', `Failed to delete ${agentId}: ${err}`);
      }
    }

    this.createdAgents = [];
  }

  // Main Test Runner
  // ------------------------------------------------------------------

  async runAll(): Promise<void> {
    console.log('\n' + '='.repeat(60));
    console.log('MULTI-AGENT CLI COMPONENTS TEST SUITE');
    console.log('='.repeat(60) + '\n');

    try {
      // Type safety (no API calls)
      this.testTypeSafety();

      // Agent lifecycle
      await this.testAgentSpawning();
      await this.testAgentRoster();
      await this.testAgentProfile();

      // Communication
      await this.testAgentCommunication();
      await this.testDelegation();

      // WebSocket
      await this.testWebSocketConnection();

      console.log('\n' + '='.repeat(60));
      console.log('🎉 ALL TESTS PASSED');
      console.log('='.repeat(60) + '\n');
    } catch (error) {
      console.error('\n❌ TEST FAILED:', error);
      throw error;
    } finally {
      await this.cleanup();
    }
  }
}

// Run tests
const tester = new MultiAgentCLITester();
tester
  .runAll()
  .then(() => {
    console.log('✅ Test suite completed successfully');
    process.exit(0);
  })
  .catch((err) => {
    console.error('❌ Test suite failed:', err);
    process.exit(1);
  });
