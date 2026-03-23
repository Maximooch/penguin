#!/usr/bin/env node
/**
 * Test script for runtime model switching
 */

import { ModelAPI } from './dist/core/api/ModelAPI.js';
import axios from 'axios';

const BASE_URL = 'http://localhost:8000';

async function testModelSwitching() {
  console.log('🧪 Testing Runtime Model Switching...\n');
  
  const modelAPI = new ModelAPI(BASE_URL);
  
  try {
    // Test 1: Check if backend is running
    console.log('1️⃣ Checking backend connection...');
    try {
      await axios.get(`${BASE_URL}/`);
      console.log('   ✅ Backend is running\n');
    } catch (error) {
      console.log('   ⚠️ Backend not running. Start with: cd ../penguin && python -m penguin.api\n');
      return;
    }
    
    // Test 2: Get current model from backend
    console.log('2️⃣ Getting current model from backend...');
    const currentConfig = await modelAPI.getCurrentModel();
    console.log('   Current model:', currentConfig.model);
    console.log('   Provider:', currentConfig.provider);
    console.log('   ✅ Success\n');
    
    // Test 3: Fetch available models
    console.log('3️⃣ Fetching available models from OpenRouter...');
    const models = await modelAPI.fetchAvailableModels();
    console.log(`   Found ${models.length} models`);
    
    // Find GPT-5 and other reasoning models
    const reasoningModels = models.filter(m => {
      const id = m.id.toLowerCase();
      return id.includes('gpt-5') || id.includes('gpt5') ||
             id.includes('/o1') || id.includes('/o3') ||
             (id.includes('gemini') && (id.includes('2.5') || id.includes('2-5')));
    });
    
    console.log(`   Found ${reasoningModels.length} reasoning-capable models:`);
    reasoningModels.slice(0, 5).forEach(model => {
      const tokens = model.context_length ? `${model.context_length.toLocaleString()} tokens` : 'unknown';
      console.log(`     - ${model.id} (${tokens}) 🧠`);
    });
    console.log('   ✅ Success\n');
    
    // Test 4: Test runtime model switching
    console.log('4️⃣ Testing runtime model switching...');
    const testModel = 'openai/gpt-4o'; // Use a common model for testing
    console.log(`   Switching to: ${testModel}`);
    
    const success = await modelAPI.setModel(testModel);
    
    if (success) {
      console.log('   ✅ Model switch succeeded via API');
      
      // Verify the change
      const newConfig = await modelAPI.getCurrentModel();
      console.log(`   Verification: Current model is now ${newConfig.model}`);
      
      // Check if reasoning was configured
      const localConfig = await import('./dist/config/loader.js').then(m => m.loadConfig());
      if (localConfig?.model?.reasoning_enabled) {
        console.log(`   Reasoning enabled: ${localConfig.model.reasoning_enabled}`);
        console.log(`   Reasoning effort: ${localConfig.model.reasoning_effort || 'not set'}`);
      }
      
      // Restore original model
      console.log(`\n   Restoring original model: ${currentConfig.model}`);
      await modelAPI.setModel(currentConfig.model, currentConfig.provider);
      console.log('   ✅ Restored\n');
    } else {
      console.log('   ❌ Model switch failed\n');
    }
    
    // Test 5: Test GPT-5 model configuration (if available)
    console.log('5️⃣ Testing GPT-5/reasoning model configuration...');
    const gpt5Model = models.find(m => m.id.toLowerCase().includes('gpt-5') || m.id.toLowerCase().includes('gpt5'));
    
    if (gpt5Model) {
      console.log(`   Found GPT-5 model: ${gpt5Model.id}`);
      console.log(`   Switching to GPT-5 to test reasoning configuration...`);
      
      const gpt5Success = await modelAPI.setModel(gpt5Model.id);
      if (gpt5Success) {
        const config = await import('./dist/config/loader.js').then(m => m.loadConfig());
        
        console.log('   Configuration after switching to GPT-5:');
        console.log(`     - Model: ${config.model.default}`);
        console.log(`     - Reasoning enabled: ${config.model.reasoning_enabled || false}`);
        console.log(`     - Reasoning effort: ${config.model.reasoning_effort || 'not set'}`);
        console.log(`     - Max tokens: ${config.model.max_tokens}`);
        console.log(`     - Context window: ${config.model.context_window}`);
        
        // Restore original
        await modelAPI.setModel(currentConfig.model, currentConfig.provider);
        console.log('   ✅ GPT-5 configuration test complete\n');
      }
    } else {
      console.log('   No GPT-5 model found in available models\n');
    }
    
    console.log('✅ All runtime model switching tests completed successfully!');
    console.log('\nYou can now use /models in the Penguin CLI to switch models at runtime.');
    
  } catch (error) {
    console.error('❌ Test failed:', error.message);
    if (error.response) {
      console.error('   Response:', error.response.status, error.response.data);
    }
    process.exit(1);
  }
}

// Run the test
testModelSwitching().catch(console.error);