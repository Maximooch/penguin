// Message parsing utilities for Penguin Web Interface
import { ActionType } from './constants';

class MessageParser {
  static parseResponse(content) {
    const result = {
      codeBlocks: [],
      executeBlocks: [],
      toolResults: [],
      plainText: content
    };

    // First handle execute blocks
    if (content.includes('<execute>')) {
      result.executeBlocks = this.parseExecuteBlocks(content);
      result.plainText = content.replace(/<execute>[\s\S]*?<\/execute>/g, '').trim();
    }

    // Then handle markdown code blocks
    if (result.plainText.includes('```')) {
      result.codeBlocks = this.parseCodeBlocks(result.plainText);
      result.plainText = result.plainText.replace(/```[\s\S]*?```/g, '').trim();
    }

    // Handle tool results
    if (content.includes('Tool Results:')) {
      result.toolResults = this.parseToolResults(content);
    }

    return result;
  }

  static parseExecuteBlocks(text) {
    const blocks = [];
    const pattern = /<execute>([\s\S]*?)<\/execute>/g;
    let match;

    while ((match = pattern.exec(text)) !== null) {
      blocks.push({
        content: match[1].trim(),
        raw: match[0]
      });
    }

    return blocks;
  }

  static parseActions(text) {
    const pattern = /<(\w+)>(.*?)<\/\1>/gs;
    const actions = [];
    let match;

    while ((match = pattern.exec(text)) !== null) {
      const actionType = match[1].toLowerCase();
      const params = match[2].trim();
      
      if (Object.values(ActionType).includes(actionType)) {
        actions.push({ type: actionType, params });
      }
    }

    return actions;
  }

  static parseCodeBlocks(text) {
    const blocks = [];
    const pattern = /```(\w+)?\n([\s\S]*?)```/g;
    let match;

    while ((match = pattern.exec(text)) !== null) {
      blocks.push({
        language: match[1] || '',
        content: match[2].trim(),
        raw: match[0]
      });
    }

    return blocks;
  }

  static parseToolResults(text) {
    const results = [];
    const lines = text.split('\n');

    for (const line of lines) {
      if (line.startsWith('• ')) {
        const [tool, ...resultParts] = line.slice(2).split(':');
        results.push({
          tool: tool.trim(),
          result: resultParts.join(':').trim()
        });
      }
    }

    return results;
  }

  static parseInlineCode(text) {
    const pattern = /`([^`]+)`/g;
    const inlineCode = [];
    let match;

    while ((match = pattern.exec(text)) !== null) {
      inlineCode.push({
        code: match[1],
        raw: match[0]
      });
    }

    return inlineCode;
  }

  static parsePlainText(text) {
    // Remove code blocks
    let cleanText = text.replace(/```[\s\S]*?```/g, '');
    // Remove inline code
    cleanText = cleanText.replace(/`[^`]+`/g, '');
    // Remove tool results
    cleanText = cleanText.replace(/^• .*$/gm, '');
    // Remove action tags
    cleanText = cleanText.replace(/<\w+>[\s\S]*?<\/\w+>/g, '');
    
    return cleanText.trim();
  }
}

export default MessageParser; 