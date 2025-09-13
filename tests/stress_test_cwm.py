#!/usr/bin/env python3
"""
Context Window Manager (CWM) Stress Test
Tests CWM performance under realistic 1-hour autonomous development workloads.

Simulates:
- 2M+ tokens/hour processing
- 500-1000 tool executions/hour
- 200-500 file operations/hour  
- 1000+ context retrievals/hour
- Continuous code generation

Usage:
  uv run stress_test_cwm.py [--mode synthetic|realistic] [--window INT] [--snapshot-interval INT]

Modes:
  synthetic (default)  - Fast budget math (legacy path). No Session/Message pipeline.
  realistic            - Session-backed flow with project docs autoload, rebalancing, and trimming.
"""

import asyncio
import argparse
import random
import time
import psutil
import os
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any
import numpy as np
import json
from collections import defaultdict
from datetime import datetime, timedelta

@dataclass
class WorkloadEvent:
    """Single event in the workload"""
    event_type: str
    tokens: int
    timestamp: float
    metadata: Dict[str, Any] = None

class RealisticHourlyWorkload:
    """Generate realistic 1-hour autonomous coding session workload"""
    
    def __init__(self, seed: int | None = None):
        self.random_seed = seed if seed is not None else 42
        random.seed(self.random_seed)
        
    def generate_intensive_hour(self) -> List[WorkloadEvent]:
        """Generate 1 hour of intensive autonomous development"""
        
        events = []
        
        # File operations - 400/hour (every 9 seconds)
        print("🔧 Generating file operations...")
        for i in range(400):
            # Mix of different file sizes
            if i % 10 == 0:  # 10% large files  
                tokens = random.randint(10000, 50000)
            elif i % 3 == 0:  # 33% medium files
                tokens = random.randint(2000, 10000) 
            else:  # 57% small files
                tokens = random.randint(200, 2000)
                
            events.append(WorkloadEvent(
                event_type='file_read',
                tokens=tokens,
                timestamp=i * 9.0,  # Every 9 seconds
                metadata={'file_size_category': 'large' if tokens > 10000 else 'medium' if tokens > 2000 else 'small'}
            ))
            
        # Tool executions - 1200/hour (every 3 seconds)
        print("⚡ Generating tool executions...")
        for i in range(1200):
            # Tool outputs vary widely
            tool_type = random.choice(['compile', 'test', 'lint', 'format', 'git', 'search'])
            
            if tool_type == 'compile':
                tokens = random.randint(500, 5000)  # Compiler output
            elif tool_type == 'test': 
                tokens = random.randint(1000, 15000)  # Test results
            elif tool_type == 'search':
                tokens = random.randint(200, 3000)  # Search results
            else:
                tokens = random.randint(100, 1000)  # Other tools
                
            events.append(WorkloadEvent(
                event_type='tool_execution',
                tokens=tokens,
                timestamp=i * 3.0,  # Every 3 seconds
                metadata={'tool_type': tool_type}
            ))
            
        # Code generation - 80 sessions/hour (every 45 seconds)
        print("💻 Generating code generation sessions...")  
        for i in range(80):
            # Code generation produces lots of tokens
            generation_type = random.choice(['function', 'class', 'module', 'refactor'])
            
            if generation_type == 'module':
                tokens = random.randint(20000, 100000)  # Whole modules
            elif generation_type == 'class':
                tokens = random.randint(5000, 30000)  # Classes
            elif generation_type == 'refactor':
                tokens = random.randint(10000, 50000)  # Refactoring
            else:  # function
                tokens = random.randint(1000, 8000)  # Functions
                
            events.append(WorkloadEvent(
                event_type='code_generation',
                tokens=tokens, 
                timestamp=i * 45.0,  # Every 45 seconds
                metadata={'generation_type': generation_type}
            ))
            
        # Context retrievals - 1800/hour (every 2 seconds)
        print("🔍 Generating context retrievals...")
        for i in range(1800):
            # Context retrieval sizes
            retrieval_type = random.choice(['symbol_lookup', 'file_search', 'history_search'])
            
            if retrieval_type == 'history_search':
                tokens = random.randint(500, 5000)  # Historical context
            else:
                tokens = random.randint(50, 1000)  # Symbol/file lookups
                
            events.append(WorkloadEvent(
                event_type='context_retrieval', 
                tokens=tokens,
                timestamp=i * 2.0,  # Every 2 seconds
                metadata={'retrieval_type': retrieval_type}
            ))
            
        # Conversation/planning - 600/hour (every 6 seconds)
        print("💬 Generating conversation turns...")
        for i in range(600):
            # Mix of user queries and assistant responses
            if i % 2 == 0:  # User queries
                tokens = random.randint(50, 500)
            else:  # Assistant responses
                tokens = random.randint(200, 3000)
                
            events.append(WorkloadEvent(
                event_type='conversation',
                tokens=tokens,
                timestamp=i * 6.0,  # Every 6 seconds
                metadata={'turn_type': 'user' if i % 2 == 0 else 'assistant'}
            ))
        
        # Sort by timestamp for realistic processing order
        events.sort(key=lambda x: x.timestamp)
        
        return events
        
    def calculate_workload_stats(self, events: List[WorkloadEvent]) -> Dict[str, Any]:
        """Calculate comprehensive workload statistics"""
        
        stats = defaultdict(lambda: {'count': 0, 'tokens': 0})
        total_tokens = 0
        
        for event in events:
            stats[event.event_type]['count'] += 1
            stats[event.event_type]['tokens'] += event.tokens
            total_tokens += event.tokens
            
        return {
            'total_events': len(events),
            'total_tokens': total_tokens,
            'duration_hours': max(event.timestamp for event in events) / 3600,
            'tokens_per_hour': total_tokens / (max(event.timestamp for event in events) / 3600),
            'events_per_hour': len(events) / (max(event.timestamp for event in events) / 3600),
            'breakdown': dict(stats)
        }

class StressTestMetrics:
    """Track performance metrics during stress test"""
    
    def __init__(self):
        self.reset()
        
    def reset(self):
        self.start_time = time.time()
        self.memory_snapshots = []
        self.processing_times = []
        self.borrowing_operations = 0
        self.trimming_operations = 0
        self.errors = []
        self.tokens_processed = 0
        self.events_processed = 0
        
        # Category-specific metrics
        self.category_tokens = defaultdict(int)
        self.category_operations = defaultdict(int)
        self.trim_by_category = defaultdict(int)
        self.borrowed_tokens_total = 0
        self.borrow_caps_hit_count = 0
        
    def record_event(self, event: WorkloadEvent, processing_time: float, category: str):
        """Record metrics for a single event"""
        self.processing_times.append(processing_time)
        self.tokens_processed += event.tokens
        self.events_processed += 1
        self.category_tokens[category] += event.tokens
        self.category_operations[category] += 1
        
    def record_memory_snapshot(self):
        """Record current memory usage"""
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024
        self.memory_snapshots.append((self.events_processed, memory_mb))
        
    def record_error(self, error_msg: str):
        """Record an error"""
        self.errors.append(f"Event {self.events_processed}: {error_msg}")
        
    def get_memory_growth_rate(self) -> float:
        """Return magnitude of memory growth rate (MB per 1000 events)."""
        slope = self.get_memory_growth_slope()
        return abs(slope)

    def get_memory_growth_slope(self) -> float:
        """Calculate signed memory growth slope (MB per 1000 events) using linear regression.

        Negative means decreasing memory over events (e.g., GC effects), positive means growth.
        """
        if len(self.memory_snapshots) < 2:
            return 0.0
        try:
            import numpy as _np
            x = _np.array([ev for ev, _mb in self.memory_snapshots], dtype=float)
            y = _np.array([mb for _ev, mb in self.memory_snapshots], dtype=float)
            # Guard against constant x
            if (x.max() - x.min()) <= 0:
                return 0.0
            # Fit y = a*x + b; slope a in MB per event
            a, b = _np.polyfit(x, y, 1)
            return float(a * 1000.0)  # MB per 1000 events
        except Exception:
            # Fallback to first-to-last estimate
            first = self.memory_snapshots[0]
            last = self.memory_snapshots[-1]
            event_diff = last[0] - first[0]
            if event_diff == 0:
                return 0.0
            memory_diff = last[1] - first[1]
            return (memory_diff / event_diff) * 1000.0
        
    def get_summary(self) -> Dict[str, Any]:
        """Get comprehensive test summary"""
        elapsed_time = time.time() - self.start_time
        
        slope = self.get_memory_growth_slope()
        direction = "increasing" if slope > 0.1 else ("decreasing" if slope < -0.1 else "stable")

        return {
            'duration': elapsed_time,
            'total_events': self.events_processed,
            'total_tokens': self.tokens_processed,
            'tokens_per_second': self.tokens_processed / elapsed_time if elapsed_time > 0 else 0,
            'events_per_second': self.events_processed / elapsed_time if elapsed_time > 0 else 0,
            'avg_processing_time_ms': np.mean(self.processing_times) * 1000 if self.processing_times else 0,
            'p95_processing_time_ms': np.percentile(self.processing_times, 95) * 1000 if self.processing_times else 0,
            'p99_processing_time_ms': np.percentile(self.processing_times, 99) * 1000 if self.processing_times else 0,
            'memory_growth_rate': self.get_memory_growth_rate(),
            'memory_growth_slope': slope,
            'memory_growth_direction': direction,
            'final_memory_mb': self.memory_snapshots[-1][1] if self.memory_snapshots else 0,
            'borrowing_operations': self.borrowing_operations,
            'borrowed_tokens_total': self.borrowed_tokens_total,
            'borrowed_tokens_avg': (self.borrowed_tokens_total / self.borrowing_operations) if self.borrowing_operations else 0,
            'trimming_operations': self.trimming_operations,
            'error_count': len(self.errors),
            'category_breakdown': dict(self.category_tokens)
        }

async def run_cwm_stress_test():
    """Main stress test execution"""
    
    print("🔥 CWM 1-Hour Stress Test")
    print("=" * 60)
    
    # Generate workload
    print("\n📊 Generating realistic workload...")
    # Seed for reproducibility
    seed_override = globals().get("__CWM_SEED__") or os.environ.get("PENGUIN_CWM_SEED")
    try:
        seed_override = int(seed_override) if seed_override is not None else None
    except Exception:
        seed_override = None
    workload_gen = RealisticHourlyWorkload(seed=seed_override)
    events = workload_gen.generate_intensive_hour()
    # Mode might reorder events into conversational turns
    pre_mode = (globals().get("__CWM_MODE__") or os.environ.get("PENGUIN_CWM_MODE") or "synthetic").lower()

    def _reorder_into_turns(evts: List[WorkloadEvent]) -> List[WorkloadEvent]:
        # Group by type
        buckets: Dict[str, List[WorkloadEvent]] = {
            'conversation': [], 'code_generation': [], 'file_read': [], 'tool_execution': [], 'context_retrieval': []
        }
        for e in evts:
            if e.event_type in buckets:
                buckets[e.event_type].append(e)
        # Simple deterministic order: conv → code → file → tool → ctx → ctx
        order = ['conversation', 'code_generation', 'file_read', 'tool_execution', 'context_retrieval', 'context_retrieval']
        # Rebuild sequence
        out: List[WorkloadEvent] = []
        idx = {k: 0 for k in buckets}
        total_target = sum(len(v) for v in buckets.values())
        while len(out) < total_target:
            for key in order:
                arr = buckets.get(key, [])
                i = idx.get(key, 0)
                if i < len(arr):
                    out.append(arr[i])
                    idx[key] = i + 1
            # break if all exhausted
            if all(idx[k] >= len(buckets[k]) for k in buckets):
                break
        # Assign uniform timestamps across an hour to preserve chronology
        n = len(out)
        if n:
            dt = 3600.0 / n
            for i, e in enumerate(out):
                e.timestamp = i * dt
        return out

    if pre_mode == 'turns':
        events = _reorder_into_turns(events)
    stats = workload_gen.calculate_workload_stats(events)
    
    print(f"\n✅ Workload generated:")
    print(f"   📈 Total events: {stats['total_events']:,}")
    print(f"   🎯 Total tokens: {stats['total_tokens']:,}")
    print(f"   ⏱️  Duration: {stats['duration_hours']:.1f} hours") 
    print(f"   🚀 Tokens/hour: {stats['tokens_per_hour']:,.0f}")
    print(f"   ⚡ Events/hour: {stats['events_per_hour']:,.0f}")
    
    print(f"\n📋 Event breakdown:")
    for event_type, breakdown in stats['breakdown'].items():
        print(f"   {event_type}: {breakdown['count']:,} events, {breakdown['tokens']:,} tokens")
    
    # Initialize CWM 
    print(f"\n🧠 Initializing Context Window Manager...")
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent / "penguin"))
        from penguin.system.context_window import ContextWindowManager

        # Try to use ConversationManager for more general import
        try:
            from penguin.conversation.conversation_manager import ConversationManager
            # Get MessageCategory from conversation manager if available
            from penguin.system.state import MessageCategory
            print("   ✅ Using ConversationManager imports")
        except ImportError:
            # Fallback to direct import
            from penguin.system.state import MessageCategory
            print("   ✅ Using direct state imports")

        # Create mock model config for realistic token budget  
        class MockModelConfig:
            def __init__(self, max_tokens):
                self.max_tokens = max_tokens
                self.max_output_tokens = 64_000  # 64k max output
        # Parse optional CLI overrides
        window_override = int(os.environ.get("PENGUIN_CWM_WINDOW", "0")) or None
        try:
            # Allow argparse-driven override via global parsed args (set later in main)
            window_override = window_override or globals().get("__CWM_WINDOW_OVERRIDE__")
        except Exception:
            pass
        model_max = int(window_override or 200_000)

        # Provide a token_counter that understands synthetic dict payloads to avoid huge strings
        def synthetic_token_counter(content: Any) -> int:
            # If caller passes a dict with a synthetic token hint, use it
            if isinstance(content, dict) and "__synthetic_tokens__" in content:
                return int(content.get("__synthetic_tokens__", 0))
            # Lists/dicts without synthetic hint: approximate lightly
            if isinstance(content, (list, dict)):
                try:
                    import json as _json
                    return len(_json.dumps(content)) // 4
                except Exception:
                    return len(str(content)) // 4
            # Strings: approximate
            if isinstance(content, str):
                return len(content) // 4
            return len(str(content)) // 4

        model_config = MockModelConfig(max_tokens=model_max)
        cwm = ContextWindowManager(model_config=model_config, token_counter=synthetic_token_counter)
        print(f"   ✅ CWM initialized with {cwm.max_tokens:,} token budget")

    except ImportError as e:
        print(f"   ❌ Failed to import CWM: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Initialize metrics tracking
    metrics = StressTestMetrics()
    alloc_snapshots: List[Dict[str, Any]] = []
    project_docs_debug: Dict[str, Any] = {}

    print(f"\n🚀 Starting stress test execution...")
    print(f"   (Processing {len(events):,} events with {stats['total_tokens']:,} tokens)")

    # Process events
    progress_interval = len(events) // 20  # 20 progress updates
    last_progress = 0
    last_progress_time = time.time()
    last_progress_tokens = 0

    # Choose execution mode
    mode = (globals().get("__CWM_MODE__") or os.environ.get("PENGUIN_CWM_MODE") or "synthetic").lower()
    snapshot_interval = int(globals().get("__CWM_SNAPSHOT_INTERVAL__") or 0) or 0
    print(f"   🧪 Mode: {mode}")

    exec_mode = "realistic" if mode in ("realistic", "turns") else mode

    if exec_mode == "realistic":
        # Realistic path: build a Session with Messages and let CWM manage trimming
        from penguin.system.state import Session, Message, MessageCategory as MC

        session = Session()

        # Load project docs (PENGUIN.md > AGENTS.md > README.md) into CONTEXT once
        project_root = Path('.').resolve()
        proj_content, proj_debug = cwm.load_project_instructions(str(project_root))
        project_docs_debug = proj_debug or {}
        if proj_content:
            msg = Message(
                role="system",
                content=proj_content,
                category=MC.CONTEXT,
            )
            session.add_message(msg)

        # Baseline time for chronological ordering
        t0 = datetime.now()

        for i, event in enumerate(events):
            event_start = time.time()

            try:
                # Map event types to categories and roles
                if event.event_type == 'file_read':
                    cat, role = MC.CONTEXT, "system"
                elif event.event_type == 'tool_execution':
                    cat, role = MC.SYSTEM_OUTPUT, "tool"
                elif event.event_type in ['code_generation', 'conversation']:
                    cat, role = MC.DIALOG, ("assistant" if event.event_type == 'code_generation' else "user")
                else:  # context_retrieval
                    cat, role = MC.CONTEXT, "system"

                # Create a synthetic content payload without allocating huge strings
                payload = {
                    "synthetic": True,
                    "event_type": event.event_type,
                    "__synthetic_tokens__": int(event.tokens),
                }

                # Build message with a deterministic timestamp
                ts = (t0 + timedelta(seconds=event.timestamp)).isoformat()
                message = Message(
                    role=role,
                    content=payload,
                    category=cat,
                    timestamp=ts,
                )
                session.add_message(message)

                # Analyze and populate budgets for current session state
                before_stats = cwm.analyze_session(session)
                cwm.reset_usage()
                for _m in session.messages:
                    cwm.update_usage(_m.category, _m.tokens)

                # Rebalance budgets before trimming to favor CONTEXT when viable
                movements = cwm.auto_rebalance_budgets()
                if movements:
                    metrics.borrowing_operations += len(movements)
                    try:
                        metrics.borrowed_tokens_total += int(sum(movements.values()))
                    except Exception:
                        pass

                # Process session through the CWM (analyze + trim if needed)
                session = cwm.process_session(session)
                after_stats = cwm.analyze_session(session)

                # Count trimming if tokens decreased
                if after_stats["total_tokens"] < before_stats["total_tokens"]:
                    metrics.trimming_operations += 1
                    # Attribute trimmed tokens by category and guard SYSTEM
                    for _cat, _before in before_stats["per_category"].items():
                        _after = after_stats["per_category"].get(_cat, 0)
                        _delta = _before - _after
                        if _delta > 0:
                            try:
                                cname = _cat.name if hasattr(_cat, 'name') else str(_cat)
                            except Exception:
                                cname = str(_cat)
                            metrics.trim_by_category[cname] += int(_delta)
                            if cname == "SYSTEM":
                                metrics.record_error("SYSTEM category tokens trimmed — invariant breach")

            except Exception as e:
                metrics.record_error(f"Processing error: {e}")

            # Record metrics
            processing_time = time.time() - event_start
            metrics.record_event(event, processing_time, cat.name)

            if processing_time > 0.01:
                metrics.record_error(f"Slow event processing: {processing_time:.3f}s")

            # Memory snapshot
            if i % 1000 == 0:
                metrics.record_memory_snapshot()
                if len(metrics.memory_snapshots) > 5:
                    growth_rate = metrics.get_memory_growth_rate()
                    if growth_rate > 50:
                        metrics.record_error(f"High memory growth: {growth_rate:.1f}MB/1000 events")

            # Optional allocation snapshot for debugging
            if snapshot_interval and (i % snapshot_interval == 0):
                try:
                    alloc = cwm.get_allocation_report()
                    alloc_snapshots.append({"event": i, "allocation": alloc})
                    # Cap snapshots to avoid runaway memory
                    if len(alloc_snapshots) > 25:
                        alloc_snapshots.pop(0)
                except Exception:
                    pass

            # Progress
            if i >= last_progress + progress_interval:
                now = time.time()
                progress = (i / len(events)) * 100
                # Windowed rate since last report
                elapsed_w = now - last_progress_time
                tokens_w = metrics.tokens_processed - last_progress_tokens
                tokens_per_sec_w = tokens_w / elapsed_w if elapsed_w > 0 else 0
                print(f"   📊 {progress:.0f}% complete - {tokens_per_sec_w:,.0f} tokens/sec, {len(metrics.errors)} errors")
                last_progress = i
                last_progress_time = now
                last_progress_tokens = metrics.tokens_processed

            # Gentle pacing
            if i % 100 == 0:
                await asyncio.sleep(0.001)

    else:
        # Legacy synthetic path: fast budget math without Session/Message
        for i, event in enumerate(events):
            event_start = time.time()

            try:
                # Map event types to message categories
                if event.event_type == 'file_read':
                    category = MessageCategory.CONTEXT
                elif event.event_type == 'tool_execution':
                    category = MessageCategory.SYSTEM_OUTPUT
                elif event.event_type in ['code_generation', 'conversation']:
                    category = MessageCategory.DIALOG
                else:  # context_retrieval
                    category = MessageCategory.CONTEXT

                # Update CWM usage
                cwm.update_usage(category, event.tokens)

                # Check for budget overruns and rebalancing
                if cwm.is_over_budget():
                    # Pre-calc caps & availability before borrow for diagnostics
                    try:
                        ctx_b = cwm.get_budget(MessageCategory.CONTEXT)
                        dlg_b = cwm.get_budget(MessageCategory.DIALOG)
                        context_over = max(0, (ctx_b.current_tokens - ctx_b.max_tokens)) if ctx_b else 0
                        dialog_available = (dlg_b.max_tokens - dlg_b.current_tokens) if dlg_b else 0
                        cap = dialog_available // 2 if dialog_available > 0 else 0
                    except Exception:
                        context_over = dialog_available = cap = 0

                    movements = cwm.auto_rebalance_budgets()
                    if movements:
                        metrics.borrowing_operations += len(movements)
                        try:
                            borrowed = int(sum(movements.values()))
                            metrics.borrowed_tokens_total += borrowed
                            # Determine if the 50% cap was the limiter
                            if cap > 0 and borrowed == cap and cap < context_over and cap <= dialog_available:
                                metrics.borrow_caps_hit_count += 1
                        except Exception:
                            pass

                    # If still over budget, simulate trimming cost
                    if cwm.is_over_budget():
                        trim_start = time.time()
                        await asyncio.sleep(0.001)
                        trim_time = time.time() - trim_start
                        metrics.trimming_operations += 1
                        if trim_time > 0.01:
                            metrics.record_error(f"Slow trimming: {trim_time:.3f}s")

            except Exception as e:
                metrics.record_error(f"Processing error: {e}")

            processing_time = time.time() - event_start
            metrics.record_event(event, processing_time, category.name)
            if processing_time > 0.01:
                metrics.record_error(f"Slow event processing: {processing_time:.3f}s")

            if i % 1000 == 0:
                metrics.record_memory_snapshot()
                if len(metrics.memory_snapshots) > 5:
                    growth_rate = metrics.get_memory_growth_rate()
                    if growth_rate > 50:
                        metrics.record_error(f"High memory growth: {growth_rate:.1f}MB/1000 events")

            if i >= last_progress + progress_interval:
                now = time.time()
                progress = (i / len(events)) * 100
                elapsed_w = now - last_progress_time
                tokens_w = metrics.tokens_processed - last_progress_tokens
                tokens_per_sec_w = tokens_w / elapsed_w if elapsed_w > 0 else 0
                print(f"   📊 {progress:.0f}% complete - {tokens_per_sec_w:,.0f} tokens/sec, {len(metrics.errors)} errors")
                last_progress = i
                last_progress_time = now
                last_progress_tokens = metrics.tokens_processed

            if i % 100 == 0:
                await asyncio.sleep(0.001)
    
    # Final metrics snapshot
    metrics.record_memory_snapshot()
    
    # Generate comprehensive report
    print(f"\n📈 Stress Test Results")
    print("=" * 60)
    
    summary = metrics.get_summary()
    
    print(f"⏱️  Performance Metrics:")
    print(f"   Duration: {summary['duration']:.2f} seconds")
    print(f"   Tokens processed: {summary['total_tokens']:,}")
    print(f"   Events processed: {summary['total_events']:,}")
    print(f"   Tokens per second: {summary['tokens_per_second']:,.0f}")
    print(f"   Events per second: {summary['events_per_second']:.1f}")
    
    print(f"\n⚡ Latency Metrics:")
    print(f"   Average event time: {summary['avg_processing_time_ms']:.2f}ms")
    print(f"   P95 event time: {summary['p95_processing_time_ms']:.2f}ms")  
    print(f"   P99 event time: {summary['p99_processing_time_ms']:.2f}ms")
    
    print(f"\n🧠 Memory Metrics:")
    print(f"   Final memory usage: {summary['final_memory_mb']:.1f}MB")
    print(f"   Memory growth trend: {summary['memory_growth_direction']} ({summary['memory_growth_slope']:+.2f}MB/1000 events)")
    print(f"   Memory growth magnitude: {summary['memory_growth_rate']:.2f}MB/1000 events")
    
    print(f"\n🔄 CWM Operations:")
    print(f"   Token borrowing operations: {summary['borrowing_operations']}")
    print(f"   Trimming operations: {summary['trimming_operations']}")
    
    print(f"\n📊 Token Distribution:")
    for category, tokens in summary['category_breakdown'].items():
        percentage = (tokens / summary['total_tokens']) * 100
        print(f"   {category}: {tokens:,} tokens ({percentage:.1f}%)")
    
    if metrics.errors:
        print(f"\n⚠️  Errors ({len(metrics.errors)} total):")
        for error in metrics.errors[:10]:  # Show first 10 errors
            print(f"   {error}")
        if len(metrics.errors) > 10:
            print(f"   ... and {len(metrics.errors) - 10} more errors")
    
    # Success criteria evaluation  
    print(f"\n🎯 Success Criteria:")

    # New criterion: forbid SYSTEM trimming
    system_trimmed = int(dict(getattr(metrics, 'trim_by_category', {})).get('SYSTEM', 0)) > 0
    criteria = {
        'Processed 2M+ tokens': summary['total_tokens'] >= 2_000_000,
        'Error rate <1%': (summary['error_count'] / summary['total_events']) < 0.01,
        'Average latency <10ms': summary['avg_processing_time_ms'] < 10.0,
        'P99 latency <100ms': summary['p99_processing_time_ms'] < 100.0,  # More lenient for 200k context
        'Memory usage <500MB': summary['final_memory_mb'] < 500,  # Lower memory limit
        'Memory growth <50MB/1000 events': summary['memory_growth_rate'] < 50,  # Tighter memory growth
        'Throughput >50k tokens/sec': summary['tokens_per_second'] > 50_000,  # More realistic for 200k
        'Trimming operations occurred': summary['trimming_operations'] > 0,  # Should trigger with 9M+ tokens in 200k context
        'Borrowing operations occurred': summary['borrowing_operations'] > 0,  # Should see dynamic reallocation
        'No SYSTEM trim': not system_trimmed,
    }
    
    passed_criteria = 0
    for criterion, passed in criteria.items():
        status = "✅" if passed else "❌"  
        print(f"   {status} {criterion}")
        if passed:
            passed_criteria += 1
    
    overall_success = passed_criteria >= len(criteria) * 0.8  # 80% criteria must pass

    print(f"\n{'🎉' if overall_success else '💥'} Overall Result: "
          f"{'SUCCESS' if overall_success else 'FAILED'} "
          f"({passed_criteria}/{len(criteria)} criteria passed)")

    # Console: per-category trim summary
    if getattr(metrics, 'trim_by_category', None):
        print("\n✂️  Trimmed tokens by category:")
        for cname, tks in dict(metrics.trim_by_category).items():
            print(f"   {cname}: {tks:,}")
        if 'SYSTEM' in metrics.trim_by_category and metrics.trim_by_category['SYSTEM'] > 0:
            print("   ⚠️  Invariant breach: SYSTEM tokens trimmed")

    # Console: allocation summary from snapshots (min->max utilization)
    if alloc_snapshots:
        peaks: Dict[str, float] = {}
        mins: Dict[str, float] = {}
        sums: Dict[str, float] = {}
        counts: Dict[str, int] = {}
        for snap in alloc_snapshots:
            try:
                cats = snap.get('allocation', {}).get('categories', {})
                for cname, info in cats.items():
                    pct = float(info.get('utilization_pct', 0.0))
                    peaks[cname] = max(peaks.get(cname, 0.0), pct)
                    mins[cname] = min(mins.get(cname, 100.0), pct)
                    sums[cname] = sums.get(cname, 0.0) + pct
                    counts[cname] = counts.get(cname, 0) + 1
            except Exception:
                continue
        if peaks:
            print("\n📈 Utilization by category (min → avg → max from snapshots):")
            for cname in sorted(peaks.keys()):
                avg = (sums.get(cname, 0.0) / counts.get(cname, 1))
                print(f"   {cname}: {mins.get(cname, 0.0):.1f}% → {avg:.1f}% → {peaks[cname]:.1f}%")

    # Build JSON report
    try:
        # Helper: convert numpy and defaultdict types to JSON-serializable primitives
        def _jsonify(obj):
            try:
                import numpy as _np  # local import to avoid global dependency in callers
                from collections import defaultdict as _dd
            except Exception:
                _np = None
                _dd = None

            if isinstance(obj, dict):
                return {str(_jsonify(k)): _jsonify(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_jsonify(v) for v in obj]
            if _np is not None:
                if isinstance(obj, (_np.integer,)):
                    return int(obj)
                if isinstance(obj, (_np.floating,)):
                    return float(obj)
                if isinstance(obj, (_np.bool_,)):
                    return bool(obj)
            if _dd is not None and isinstance(obj, _dd):
                return {k: _jsonify(v) for k, v in obj.items()}
            return obj

        # Build report structure
        # Build allocation min/max summary from snapshots
        alloc_minmax: Dict[str, Dict[str, float]] = {}
        if alloc_snapshots:
            mins: Dict[str, float] = {}
            peaks: Dict[str, float] = {}
            for snap in alloc_snapshots:
                try:
                    cats = snap.get('allocation', {}).get('categories', {})
                    for cname, info in cats.items():
                        pct = float(info.get('utilization_pct', 0.0))
                        peaks[cname] = max(peaks.get(cname, 0.0), pct)
                        mins[cname] = min(mins.get(cname, 100.0), pct)
                except Exception:
                    continue
            alloc_minmax = {k: {"min_pct": mins.get(k, 0.0), "max_pct": peaks.get(k, 0.0)} for k in peaks.keys()}

        report = {
            "timestamp": datetime.now().isoformat(),
            "mode": mode,
            "window_tokens": cwm.max_tokens,
            "snapshot_interval": snapshot_interval,
            "workload": {
                "total_events": stats['total_events'],
                "total_tokens": stats['total_tokens'],
                "duration_hours": stats['duration_hours'],
                "tokens_per_hour": stats['tokens_per_hour'],
                "events_per_hour": stats['events_per_hour'],
                "breakdown": {k: v for k, v in stats['breakdown'].items()},
            },
            "summary": {
                **summary,
                "trim_by_category": dict(getattr(metrics, 'trim_by_category', {})),
                "borrow_caps_hit_count": getattr(metrics, 'borrow_caps_hit_count', 0),
            },
            "criteria": {k: bool(v) for k, v in criteria.items()},
            "criteria_passed": passed_criteria,
            "overall_success": overall_success,
            "project_docs": {
                "loaded_files": project_docs_debug.get('loaded_files', []),
                "total_tokens": project_docs_debug.get('total_tokens', 0),
            },
            "allocation_snapshots": alloc_snapshots,
            "allocation_minmax": alloc_minmax,
        }

        # Destination path
        report_path = globals().get("__CWM_REPORT_PATH__")
        if not report_path:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            report_path = f"cwm_stress_report_{mode}_{ts}.json"

        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(_jsonify(report), f, indent=2)
        print(f"\n📝 Report saved to {report_path}")
    except Exception as e:
        print(f"\n⚠️  Failed to write JSON report: {e}")

    return overall_success

if __name__ == "__main__":
    print("Context Window Manager Stress Test")
    print("Simulating 1 hour of intensive autonomous development")
    print()

    # CLI args
    parser = argparse.ArgumentParser(description="CWM stress test")
    # Dynamic default: realistic locally, synthetic on CI
    default_mode = "synthetic" if (os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS")) else "realistic"
    parser.add_argument("--mode", choices=["synthetic", "realistic", "turns"], default=default_mode, help="execution mode")
    parser.add_argument("--window", type=int, default=0, help="override context window tokens (default 200k)")
    parser.add_argument("--snapshot-interval", type=int, default=0, help="allocation snapshot interval (realistic mode)")
    parser.add_argument("--report", type=str, default="", help="path to write JSON report (default: ./cwm_stress_report_<ts>.json)")
    parser.add_argument("--csv", type=str, default="", help="optional path to write a compact CSV summary")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducible workloads")
    args = parser.parse_args()

    # Share flags to the coroutine without changing signature
    globals()["__CWM_MODE__"] = args.mode
    globals()["__CWM_WINDOW_OVERRIDE__"] = args.window if args.window > 0 else None
    globals()["__CWM_SNAPSHOT_INTERVAL__"] = args.snapshot_interval if args.snapshot_interval > 0 else None
    globals()["__CWM_REPORT_PATH__"] = args.report if args.report else None
    globals()["__CWM_SEED__"] = args.seed if args.seed is not None else None

    # Run the async stress test
    try:
        success = asyncio.run(run_cwm_stress_test())
        # Emit CSV summary if requested
        if args.csv:
            try:
                import csv
                # Build a compact one-row summary
                # Re-open the JSON to pull standardized keys
                report_path = args.report if args.report else None
                if not report_path:
                    # If no report path was provided, use the last generated default name
                    # Rebuild the same default name used earlier
                    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                    report_path = f"cwm_stress_report_{args.mode}_{ts}.json"
                data = {}
                try:
                    with open(report_path, 'r', encoding='utf-8') as jf:
                        data = json.load(jf)
                except Exception:
                    data = {}

                summ = data.get('summary', {})
                trim = summ.get('trim_by_category', {})
                row = {
                    'timestamp': data.get('timestamp'),
                    'mode': data.get('mode'),
                    'window_tokens': data.get('window_tokens'),
                    'total_events': data.get('workload', {}).get('total_events'),
                    'total_tokens': data.get('workload', {}).get('total_tokens'),
                    'duration_s': summ.get('duration'),
                    'tokens_per_second': summ.get('tokens_per_second'),
                    'events_per_second': summ.get('events_per_second'),
                    'avg_ms': summ.get('avg_processing_time_ms'),
                    'p95_ms': summ.get('p95_processing_time_ms'),
                    'p99_ms': summ.get('p99_processing_time_ms'),
                    'final_mem_mb': summ.get('final_memory_mb'),
                    'mem_growth_mag_mb_per_1k': summ.get('memory_growth_rate'),
                    'mem_growth_slope_mb_per_1k': summ.get('memory_growth_slope'),
                    'mem_growth_dir': summ.get('memory_growth_direction'),
                    'borrowing_ops': summ.get('borrowing_operations'),
                    'borrowed_tokens_total': summ.get('borrowed_tokens_total'),
                    'borrowed_tokens_avg': summ.get('borrowed_tokens_avg'),
                    'trimming_ops': summ.get('trimming_operations'),
                    'trim_CONTEXT': trim.get('CONTEXT', 0),
                    'trim_DIALOG': trim.get('DIALOG', 0),
                    'trim_SYSTEM_OUTPUT': trim.get('SYSTEM_OUTPUT', 0),
                }
                # Write CSV
                with open(args.csv, 'w', newline='', encoding='utf-8') as cf:
                    writer = csv.DictWriter(cf, fieldnames=list(row.keys()))
                    writer.writeheader()
                    writer.writerow(row)
                print(f"🧾 CSV summary saved to {args.csv}")
            except Exception as e:
                print(f"⚠️  Failed to write CSV: {e}")
        exit_code = 0 if success else 1
        print(f"\nExiting with code {exit_code}")
        exit(exit_code)
    except KeyboardInterrupt:
        print("\n⏹️  Test interrupted by user")
        exit(130)
    except Exception as e:
        print(f"\n💥 Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
