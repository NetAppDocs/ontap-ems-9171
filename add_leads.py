#!/usr/bin/env python3
"""
Script to add [.lead] statements to all adoc files in the ontap-ems-9171-internal repo.
- For files that exist in ontap-ems/clean-lipi: use the lead from that branch
- For new files: generate a lead from the file content
"""

import os
import re
import time
import urllib.request
import urllib.error

REPO_DIR = "/Users/bnorberg/ontap-ems-9171-internal"
REMOTE_BASE = "https://raw.githubusercontent.com/NetAppDocs/ontap-ems/clean-lipi/"

# Track results
results = {"remote": [], "generated": [], "skipped": [], "error": []}


def extract_remote_lead(content):
    """Extract [.lead] text from remote file content."""
    match = re.search(r'\[\.lead\]\n(.+?)(?:\n\n|\n==)', content, re.DOTALL)
    if match:
        lead_text = match.group(1).strip()
        # Collapse any internal line breaks into spaces
        lead_text = ' '.join(lead_text.split())
        return lead_text
    return None


def shorten_sentence(text, max_words=25):
    """Return text truncated to the first sentence if it's very long."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    first = sentences[0].rstrip('.').rstrip()
    words = first.split()
    if len(words) > max_words:
        words = words[:max_words]
        return ' '.join(words) + '...'
    return first


def generate_lead(content):
    """Generate a [.lead] sentence from local file content."""
    # Get title
    title_match = re.search(r'^= (.+)$', content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "These events"

    # Collect all descriptions and corrective actions
    descriptions = re.findall(
        r'\*Description\*::\n(.*?)(?=\n\*|\Z)', content, re.DOTALL)
    corrective_actions = re.findall(
        r'\*Corrective Action\*::\n(.*?)(?=\n\*|\Z)', content, re.DOTALL)

    # Normalize whitespace
    descs = [' '.join(d.split()) for d in descriptions if d.strip()]
    cas = [' '.join(c.split()) for c in corrective_actions
           if c.strip() and c.strip().lower() not in ('(none).', '(none)', 'none.', 'none')]

    # Build lead
    if descs:
        # Strip common prefix from description
        desc = descs[0]
        desc = re.sub(r'^This message (occurs|is generated) when ', '', desc, flags=re.IGNORECASE)
        desc = re.sub(r'^This event (occurs|is generated) when ', '', desc, flags=re.IGNORECASE)
        desc_short = shorten_sentence(desc)
    else:
        desc_short = "an internal condition is detected"

    if cas:
        ca = cas[0]
        # Check if it contains "no action" / "no corrective" patterns
        no_action_patterns = [
            r'no (corrective action|action) (is )?required',
            r'no user action (is )?required',
            r'this is for informational',
            r'informational (only|message)',
        ]
        no_action = any(re.search(p, ca, re.IGNORECASE) for p in no_action_patterns)

        if no_action:
            corrective_phrase = "no corrective action is required"
        else:
            ca_short = shorten_sentence(ca, max_words=20)
            corrective_phrase = f"corrective action may be needed: {ca_short.lower()}"
    else:
        corrective_phrase = None

    # Compose the lead
    desc_short = desc_short.rstrip('.').rstrip()
    lead = f"{title} events are presented when {desc_short}"
    if corrective_phrase:
        lead = f"{lead} and {corrective_phrase}."
    else:
        lead += "."

    return lead


def process_file(filename):
    """Process a single adoc file."""
    filepath = os.path.join(REPO_DIR, filename)

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Skip if already has [.lead]
    if '[.lead]' in content:
        results["skipped"].append(filename)
        return "skipped (already has [.lead])"

    # --- Try remote first ---
    remote_lead = None
    remote_url = REMOTE_BASE + filename
    try:
        req = urllib.request.Request(
            remote_url,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status == 200:
                remote_content = response.read().decode('utf-8')
                remote_lead = extract_remote_lead(remote_content)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            results["error"].append((filename, f"HTTP {e.code}"))
            return f"error: HTTP {e.code}"
    except Exception as e:
        results["error"].append((filename, str(e)))
        return f"error: {e}"

    # --- Determine lead text ---
    if remote_lead:
        lead_text = remote_lead
        source = "remote"
    else:
        lead_text = generate_lead(content)
        source = "generated"

    # --- Replace [role="lead"] block ---
    # Pattern: [role="lead"] on its own line, followed by one or more text lines,
    # terminated by a blank line.
    new_content = re.sub(
        r'\[role="lead"\]\n[^\n]+(?:\n[^\n]+)*?(?=\n\n)',
        f'[.lead]\n{lead_text}',
        content,
        count=1
    )

    if new_content == content:
        # Fallback: just do a simple line replacement
        lines = content.split('\n')
        new_lines = []
        skip_next = False
        for i, line in enumerate(lines):
            if skip_next:
                skip_next = False
                continue
            if line == '[role="lead"]':
                new_lines.append('[.lead]')
                new_lines.append(lead_text)
                skip_next = True  # skip the old lead line
            else:
                new_lines.append(line)
        new_content = '\n'.join(new_lines)

    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        results[source].append(filename)
        return f"updated ({source})"
    else:
        results["error"].append((filename, "no change made"))
        return "no change (check manually)"


def main():
    # Get all adoc files except legal-notices.adoc
    adoc_files = sorted([
        f for f in os.listdir(REPO_DIR)
        if f.endswith('.adoc') and f != 'legal-notices.adoc'
    ])

    total = len(adoc_files)
    print(f"Processing {total} files...\n")

    for i, filename in enumerate(adoc_files, 1):
        outcome = process_file(filename)
        if i % 50 == 0 or i == total:
            print(f"  [{i}/{total}] {filename} -> {outcome}")
        # Light throttle to avoid hammering GitHub
        time.sleep(0.05)

    print(f"\n=== Results ===")
    print(f"  Updated from remote:   {len(results['remote'])}")
    print(f"  Generated (new files): {len(results['generated'])}")
    print(f"  Already had [.lead]:   {len(results['skipped'])}")
    print(f"  Errors:                {len(results['error'])}")

    if results['generated']:
        print(f"\n--- Files with generated leads (not in ontap-ems/clean-lipi) ---")
        for f in results['generated']:
            print(f"  {f}")

    if results['error']:
        print(f"\n--- Errors ---")
        for f, msg in results['error']:
            print(f"  {f}: {msg}")


if __name__ == "__main__":
    main()
