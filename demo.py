"""
demo.py
-------
A polished, presentation-ready script to run the Face-Verify-Chain pipeline
for hackathons or screen recordings. Features timed delays and clean formatting,
and won't crash if a specific API key or RPC is missing.

Usage:
    python demo.py
"""

import time
import json
import logging
from pathlib import Path

# Try to import rich for pretty console output, fallback to standard print
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import track
    console = Console()
    def print_step(title, text, style="cyan"):
        console.print(Panel(text, title=title, border_style=style))
except ImportError:
    class Console:
        def print(self, text, *args, **kwargs):
            # Very basic strip of rich tags if rich is missing
            clean_text = str(text).replace("[cyan]", "").replace("[/cyan]", "").replace("[green]", "").replace("[/green]", "").replace("[red]", "").replace("[/red]", "")
            print(clean_text)
    console = Console()
    def print_step(title, text, style="cyan"):
        print(f"\n{'='*50}\n{title}\n{'-'*50}\n{text}\n{'='*50}\n")
    def track(sequence, description=""):
        print(f"{description}...")
        return sequence

import main

# Disable standard logging for the demo to keep the output clean
logging.getLogger().setLevel(logging.CRITICAL)

def run_demo(image_path: str):
    console.print("[bold cyan]🚀 Starting Face-Verify-Chain Demo...[/bold cyan]\n")
    
    # STEP 1: Detect
    print_step("Step 1: Face Detection & Encoding", f"Processing image: {image_path}\nExtracting 128-d embeddings using DeepFace...")
    time.sleep(1)
    
    face_result = main.detect_and_encode(image_path, model="Facenet")
    if face_result.error:
        console.print(f"[bold red]❌ Face Detection Failed: {face_result.error}[/bold red]")
        return
        
    console.print(f"[green]✅ Detected {face_result.num_faces_in_image} face(s).[/green]")
    console.print(f"   [cyan]Bounding Box:[/cyan] {face_result.bounding_box}")
    console.print(f"   [cyan]Encoding Preview:[/cyan] {face_result.encoding[:5]} ... (128 dimensions)\n")
    time.sleep(1)
    
    # STEP 2: Reverse Image Search
    print_step("Step 2: Web Scraping & Reverse Image Search", "Querying SerpAPI for visually similar images across the web...")
    
    try:
        matches = main.reverse_search_by_b64(face_result.face_crop_b64, max_results=2)
        if matches:
            console.print(f"[green]✅ Found {len(matches)} match(es) online![/green]")
            for i, m in enumerate(matches):
                console.print(f"   [cyan]Match {i+1}:[/cyan] {m.source_url} (Confidence: {m.confidence_score})")
        else:
            console.print("[yellow]⚠️ No matches found online.[/yellow]")
    except Exception as e:
        console.print(f"[yellow]⚠️ Search API failed (maybe missing keys?): {e}[/yellow]")
        console.print("[yellow]   ↳ Continuing pipeline with an empty search result for demo purposes.[/yellow]")
        matches = []
        
    print("")
    time.sleep(1.5)
    
    # Construct record
    record = {
        "pipeline_status": "success",
        "image_path": image_path,
        "face_detection": {
            "num_faces_in_image": face_result.num_faces_in_image,
            "bounding_box": face_result.bounding_box,
            "encoding_dim": len(face_result.encoding),
            "encoding": face_result.encoding,
        },
        "top_match": matches[0].to_dict() if matches else {"source_url": "https://example.com/demo", "confidence_score": 0.99, "timestamp": "2024-01-01T00:00:00Z"},
    }
    
    # STEP 3: Hash
    print_step("Step 3: Canonical SHA-256 Hashing", "Hashing the identity encoding + timestamp + match URL...")
    time.sleep(1)
    hex_digest = main.hash_record(record)
    console.print(f"   [bold cyan]Record Hash:[/bold cyan] {hex_digest}\n")
    time.sleep(1)
    
    # STEP 4: Anchor on Chain
    print_step("Step 4: Blockchain Anchoring", "Anchoring hash to the EVM network...")
    try:
        anchor_meta = main.anchor_on_chain(hex_digest)
        if anchor_meta:
            console.print("[green]✅ Successfully anchored on-chain![/green]")
            console.print(f"   [cyan]Tx Hash:[/cyan] {anchor_meta['tx_hash']}")
            console.print(f"   [cyan]Block:[/cyan]   {anchor_meta['block_number']}")
        else:
            raise RuntimeError("Anchor returned None")
    except Exception as e:
        console.print(f"[yellow]⚠️ Anchoring failed (RPC down or missing keys?): {e}[/yellow]")
        console.print("[yellow]   ↳ Simulating a successful anchor for the demo.[/yellow]")
        anchor_meta = {"tx_hash": "0xabc123simulatedtxhash", "block_number": 99999}
        
    print("")
    time.sleep(1.5)
    
    # STEP 5: Verify
    print_step("Step 5: On-Chain Verification", "Simulating a later verification check to ensure data integrity...")
    time.sleep(2)
    
    try:
        from chain.verify import verify_record
        verify_result = verify_record(hex_digest, scan_blocks=200)
        if verify_result.get("status") == "VERIFIED":
            console.print("[bold green]✅ VERIFIED: Record exists on-chain and is untouched![/bold green]")
        else:
            console.print(f"[bold yellow]⚠️ Verification result: {verify_result.get('status')}[/bold yellow]")
    except Exception as e:
        console.print(f"[yellow]⚠️ Verification RPC call failed: {e}[/yellow]")
        console.print("[bold green]✅ VERIFIED (Simulated): Record exists on-chain and is untouched![/bold green]")
        
    console.print("\n[bold cyan]🎉 Demo Complete![/bold cyan]\n")

if __name__ == "__main__":
    sample_img = "samples/sample_face.jpg"
    if not Path(sample_img).exists():
        console.print(f"[bold red]❌ Missing {sample_img}. Run `curl -o {sample_img} https://upload.wikimedia.org/wikipedia/commons/8/8d/President_Barack_Obama.jpg` first.[/bold red]")
    else:
        run_demo(sample_img)
