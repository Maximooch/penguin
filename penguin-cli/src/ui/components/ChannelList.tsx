import React from 'react';
import { Box, Text } from 'ink';

export interface Channel {
  id: string;
  name: string;
  unreadCount?: number;
  agentCount?: number;
}

export interface ChannelListProps {
  channels: Channel[];
  selectedChannelId?: string;
  onSelect?: (channelId: string) => void;
  maxHeight?: number;
}

export function ChannelList({ channels, selectedChannelId, onSelect, maxHeight = 8 }: ChannelListProps) {
  // Sort channels: default channels first, then alphabetically
  const sortedChannels = [...channels].sort((a, b) => {
    const defaultChannels = ['#general', '#team', '#engineering'];
    const aIsDefault = defaultChannels.includes(a.id);
    const bIsDefault = defaultChannels.includes(b.id);

    if (aIsDefault && !bIsDefault) return -1;
    if (!aIsDefault && bIsDefault) return 1;
    return a.name.localeCompare(b.name);
  });

  const displayedChannels = maxHeight ? sortedChannels.slice(0, maxHeight) : sortedChannels;
  const hasMore = sortedChannels.length > displayedChannels.length;

  return (
    <Box flexDirection="column" width={18} marginTop={2}>
      <Box marginBottom={1}>
        <Text bold color="cyan">
          CHANNELS ({channels.length})
        </Text>
      </Box>

      {displayedChannels.length === 0 ? (
        <Box>
          <Text dimColor>No channels</Text>
        </Box>
      ) : (
        <Box flexDirection="column">
          {displayedChannels.map((channel) => {
            const isSelected = channel.id === selectedChannelId;
            const hasUnread = (channel.unreadCount ?? 0) > 0;

            return (
              <Box key={channel.id} marginBottom={0}>
                <Text
                  color={isSelected ? 'cyan' : hasUnread ? 'yellow' : 'white'}
                  bold={isSelected || hasUnread}
                  dimColor={!isSelected && !hasUnread}
                >
                  {channel.name}
                  {hasUnread && ` (${channel.unreadCount})`}
                </Text>
              </Box>
            );
          })}

          {hasMore && (
            <Box marginTop={1}>
              <Text dimColor>
                +{sortedChannels.length - displayedChannels.length} more
              </Text>
            </Box>
          )}
        </Box>
      )}
    </Box>
  );
}
