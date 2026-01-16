#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# find_caller_chain.py
# reads a VizTracer JSON output file and finds the call chain leading to a target function

import json
import re
import click
from collections import defaultdict
from typing import List, Dict, Tuple, Optional
from rich.console import Console
from rich.theme import Theme
from rich.table import Table, box
from rich.text import Text
from pydantic import BaseModel
from pathlib import Path

# Custom theme for console output
output_theme = Theme({
    "target": "bold red",
    "header": "bold blue",
    "chain": "bold green",
    "count": "bold yellow",
    "path": "dim"
})

console = Console(theme=output_theme)

# Pydantic models for JSON schema
class CallerInfo(BaseModel):
    name: str
    file: Optional[str] = None
    line: Optional[int] = None

class CallChain(BaseModel):
    callers: List[CallerInfo]
    occurrences: int
    percentage: float

class AnalysisResult(BaseModel):
    target_pattern: str
    total_invocations: int
    call_chains: List[CallChain]
    max_context_depth: int
    files: Optional[Dict[str, str]] = None

def parse_event(full_name: str) -> Dict[str, str]:
    """Extract method name and location from event name"""
    result = {"name": full_name.strip()}
    if ('(' in full_name and ')' in full_name):
        result["name"] = full_name.split('(')[0].strip()
        location = full_name.split('(')[1].split(')')[0]
        if ':' in location:
            result["file"], line_str = location.rsplit(':', 1)
            try:
                result["line"] = int(line_str)
            except ValueError:
                pass
        else:
            result["file"] = location
    return result

def load_and_filter_events(trace_file: str) -> List[Dict]:
    """Load and filter trace events"""
    try:
        with open(trace_file) as f:
            data = json.load(f)
        return [
            e for e in data.get("traceEvents", [])
            if e.get("ph") == "X" and "name" in e and "ts" in e and "dur" in e
        ]
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON file")
    except FileNotFoundError:
        raise ValueError(f"File '{trace_file}' not found")

def find_target_invocations(events: List[Dict], pattern: re.Pattern, max_chains: int) -> List[Tuple[int, Dict]]:
    """Find all invocations matching the target pattern"""
    tgt_invokes = []
    for i, e in enumerate(events):
        if pattern.search(parse_event(e["name"])["name"]):
            tgt_invokes.append((i, e))
            if len(tgt_invokes) >= max_chains:
                break
    return tgt_invokes

def reconstruct_call_chains(events: List[Dict], targets: List[Tuple[int, Dict]], 
                            context_size: int, max_chains: int) -> List[Dict]:
    """Reconstruct call chains for each target invocation"""
    call_chains = defaultdict(list)
    
    for target_idx, target_event in targets:
        call_stack = []
        target_start = target_event["ts"]
        
        for event in events[:target_idx]:
            if event["ts"] <= target_start <= (event["ts"] + event["dur"]):
                call_stack.append(event)
        
        # Get the context_size most relevant callers (top-level first)
        callers = [parse_event(e["name"]) for e in call_stack[-context_size:]]
        chain_key = json.dumps([c["name"] for c in callers])  # Use JSON for hashability
        call_chains[chain_key].append({
            "callers": callers,
            "target": parse_event(target_event["name"])
        })
    
    return [
        {
            "callers": chains[0]["callers"],
            "occurrences": len(chains),
            "target": chains[0]["target"]
        }
        for chains in call_chains.values()
    ]

def print_verbose_results(target_pattern: str, result: AnalysisResult):
    """Print the analysis results with rich formatting"""
    # Create summary table
    summary = Table(
        title=f"Call Chain Analysis for '{target_pattern}'",
        show_header=True,
        box=box.ROUNDED,
        show_lines=True
    )
    summary.add_column("Call Chain", style="chain")
    summary.add_column("Occurrences", style="count", justify="right")
    summary.add_column("Percentage", style="count", justify="right")
    
    for chain in sorted(result.call_chains, key=lambda x: -x.occurrences):
        percentage = f"{chain.percentage:.1%}"
        
        # Format chain with proper newlines
        formatted_chain = Text()
        for i, caller in enumerate(chain.callers):
            if i > 0:
                formatted_chain.append("\n→ ", style="dim")
            caller_text = caller.name
            if caller.file:
                caller_text += f" ({caller.file})"
            formatted_chain.append(caller_text, style="path")
        
        # Add target marker
        formatted_chain.append("\n→ ", style="dim")
        formatted_chain.append("[TARGET]", style="target bold")
        
        summary.add_row(formatted_chain, str(chain.occurrences), percentage)
    
    console.print()
    console.print(f"Analyzed [bold]{result.total_invocations}[/bold] invocations matching '[bold]{target_pattern}[/bold]'")
    console.print(summary)
    console.print(f"\n[dim]Note: Showing max {result.max_context_depth} levels of call context[/dim]")

def extract_file_contents(trace_file: str, call_chains: List[CallChain]) -> List[Tuple[str, str]]:
    """
    Extract file contents from the trace file
    For each call_chain, walk from the bottom of the stack upwards
    to find the first test file (TestClass.test_method_abc) and extract its content
    """
    try:
        with open(trace_file) as f:
            data = json.load(f)
        files = data.get("file_info", {}).get("files", {})

        test_file_paths = set()
        for chain in call_chains:
            # Start from the bottom of the stack (deepest call) and work our way up
            for caller in reversed(chain.callers):
                if caller.file and (
                    # Common patterns for test files
                    "test_" in caller.name.lower() or 
                    caller.name.startswith("Test")
                ):
                    if caller.file in files:
                        test_file_paths.add(caller.file)
                        break  # Found a test file in this chain
                    else:
                        console.print(f"[yellow]Warning: File '{caller.file}' not found in trace data[/yellow]")

        # Return list of tuples (file_path, file_content) for identified test files
        # [0] to access the file content, [1] to access the line number
        return [(path, files[path][0]) for path in test_file_paths if path in files]
    except Exception as e:
        console.print(f"[red]Error extracting file contents: {e}[/red]")
        return []

@click.command()
@click.argument("trace_file", type=click.Path(exists=True, path_type=Path))
@click.argument("target_pattern")
@click.option("--context-size", default=15, help="Number of callers to show in chain", show_default=True)
@click.option("--verbose", is_flag=False, help="Show rich console output")
@click.option("--output", type=click.Path(path_type=Path), help="Save JSON output to file")
@click.option("--max-chains", default=500, help="Max number of call chains to parse", show_default=True)
def analyze(trace_file: Path, target_pattern: str, context_size: int, 
            verbose: bool, output: Optional[Path], max_chains: int):
    """
    Analyze VizTracer logs to show call chains leading to target function.
    
    TRACE_FILE: Path to VizTracer JSON output file\n
    TARGET_PATTERN: Regex pattern to match target function name
    """
    try:
        pattern = re.compile(target_pattern)
    except re.error as e:
        console.print(f"[red]Error: Invalid regex pattern - {e}[/red]")
        raise click.Abort()
    
    try:
        events = load_and_filter_events(trace_file)
        events.sort(key=lambda x: (x["ts"], -x["dur"]))
        
        targets = find_target_invocations(events, pattern, max_chains)
        if not targets:
            console.print(f"[yellow]No invocations matched pattern '{target_pattern}'[/yellow]")
            return
            
        raw_chains = reconstruct_call_chains(events, targets, context_size, max_chains)
        total = len(targets)

        call_chains=[
                CallChain(
                    callers=[CallerInfo(**caller) for caller in chain["callers"]],
                    occurrences=chain["occurrences"],
                    percentage=chain["occurrences"] / total
                )
                for chain in raw_chains
        ]
        
        # Convert to Pydantic model
        result = AnalysisResult(
            target_pattern=target_pattern,
            total_invocations=total,
            call_chains=call_chains,
            max_context_depth=max(len(chain["callers"]) for chain in raw_chains),
            files={file: content for file, content in extract_file_contents(trace_file, call_chains)}
        )
        
        # Output results
        if verbose:
            print_verbose_results(target_pattern, result)
        
        # Use model_dump_json() for Pydantic v2 compatibility
        json_output = result.model_dump_json(indent=2)
        if output:
            output.write_text(json_output)
            if verbose:
                console.print(f"\n[green]✓ Saved JSON output to {output}[/green]")
        else:
            if not verbose:  # Only print JSON if not in verbose mode
                console.print(json_output)
        
    except Exception as e:
        console.print(f"[red]Error analyzing trace: {e}[/red]")
        raise click.Abort()

if __name__ == "__main__":
    analyze()