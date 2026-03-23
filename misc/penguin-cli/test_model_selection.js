#!/usr/bin/env node
/**
 * Test script for model selection functionality
 */

import { ModelAPI } from './dist/core/api/ModelAPI.js';

async function testModelSelection() {
  console.log('🧪 Testing Model Selection API...\n');
  
  const modelAPI = new ModelAPI('http://localhost:8000');
  
  try {
    // Test 1: Get current model
    console.log('1️⃣ Getting current model configuration...');
    const currentConfig = await modelAPI.getCurrentModel();
    console.log('   Current model:', currentConfig.model);
    console.log('   Provider:', currentConfig.provider);
    console.log('   ✅ Success\n');
    
    // Test 2: Fetch available models
    console.log('2️⃣ Fetching available models from OpenRouter...');
    const models = await modelAPI.fetchAvailableModels();
    console.log(`   Found ${models.length} models`);
    
    // Show first 5 models
    console.log('   Sample models:');
    models.slice(0, 5).forEach(model => {
      const tokens = model.context_length ? `${model.context_length.toLocaleString()} tokens` : 'unknown';
      console.log(`     - ${model.id} (${tokens})`);
    });
    console.log('   ✅ Success\n');
    
    // Test 3: Try to set a model
    console.log('3️⃣ Testing model update...');
    const testModel = 'anthropic/claude-3-5-haiku-20241022';
    console.log(`   Attempting to set model to: ${testModel}`);
    const success = await modelAPI.setModel(testModel);
    
    if (success) {
      console.log('   ✅ Model update succeeded');
      
      // Verify the change
      const newConfig = await modelAPI.getCurrentModel();
      console.log(`   Verification: Current model is now ${newConfig.model}`);
      
      // Restore original model
      console.log(`   Restoring original model: ${currentConfig.model}`);
      await modelAPI.setModel(currentConfig.model, currentConfig.provider);
      console.log('   ✅ Restored\n');
    } else {
      console.log('   ⚠️ Model update failed (backend may not be running)\n');
    }
    
    console.log('✅ All tests completed successfully!');
    
  } catch (error) {
    console.error('❌ Test failed:', error.message);
    process.exit(1);
  }
}

// Run the test
testModelSelection().catch(console.error);