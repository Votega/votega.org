#!/usr/bin/env python3
"""Budget topic (Phase 2 surfaces): the generator, topics.yml, page stub and place
section agree on one slug, and a budget mention is emitted from a tagged meeting.

Run: python scripts/test_budget_topic_surfaces.py      (no packages, no network)
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from generate_topic_mentions import TOPICS, topic_hit

failures = []


def check(name, got, want):
    if got != want:
        failures.append('%s: got %r want %r' % (name, got, want))


def read(*p):
    with open(os.path.join(ROOT, *p), encoding='utf-8') as fh:
        return fh.read()


print("slug is one string everywhere")
# topics.yml is read with a regex, not PyYAML: the CI test job installs no packages.
yml = {}
body = read('_data', 'topics.yml').split('\ntopics:\n', 1)[1]
for block in re.split(r'^  - slug: ', body, flags=re.M)[1:]:
    slug, _, rest = block.partition('\n')
    fields = {'slug': slug.strip()}
    for k in ('name', 'phrase', 'emoji', 'icon', 'blurb', 'definition', 'order'):
        mm = re.search(r'^    %s: (.+)$' % k, rest, re.M)
        fields[k] = mm.group(1).strip() if mm else None
    if fields['order']:
        fields['order'] = int(fields['order'])
    yml[slug.strip()] = fields
topics = list(yml.values())
check("generator and topics.yml carry the same slugs", set(TOPICS), set(yml))
b = yml['budget']
for field in ('name', 'phrase', 'icon', 'blurb', 'definition', 'order', 'emoji'):
    check("budget has %s" % field, bool(b.get(field)), True)
check("budget orders after local-taxes", b['order'] > yml['local-taxes']['order'], True)
check("orders unique", len({t['order'] for t in topics}), len(topics))

stub = read('local', 'topics', 'budget.html')
check("stub names the topic", re.search(r'^topic: budget$', stub, re.M) is not None, True)
check("stub permalink", '/local/topics/budget/' in stub, True)

print("place section and hub pill")
check("place page styles .sub-budget", '.sub-budget' in read('_includes', 'entity', 'place.html'), True)
check("place script renders budgetItems", 'budgetItems' in read('assets', 'scripts', 'local-subjects.js'), True)
hub = read('local.html')
check("hub ranks budgetCount", "key: 'budgetCount'" in hub, True)
check("millage special case gone", 'millageCount' not in hub, True)
tokens = read('assets', 'css', 'tokens.css')
for role in ('', '-tint', '-line'):
    check("token --color-watch-budget%s" % role, '--color-watch-budget%s:' % role in tokens, True)

print("topic_hit emits budget mentions")
m = {'date': '2026-06-02', 'body': 'Board of Commissioners', 'topics': {'budget': 1},
     'matchedTerms': ['budget hearing', 'splost'],
     'topicExcerpts': {'budget': {'excerpt': 'Public hearing on the FY27 budget', 'term': 'budget hearing'}},
     'sourceUrl': 'https://example.gov/a.pdf', 'textMethod': 'pdftotext'}
hit = topic_hit('budget', m)
check("mention built", hit is not None, True)
check("terms limited to budget lexicon", hit['terms'], ['budget hearing'])
check("excerpt carried", hit['excerpt'], 'Public hearing on the FY27 budget')
check("untagged meeting yields nothing", topic_hit('budget', dict(m, topics={'local-taxes': 1})), None)

if failures:
    print('\n'.join('FAIL ' + f for f in failures))
    sys.exit(1)
print('ok')
