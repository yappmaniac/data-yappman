#!/usr/bin/env python3
"""One-off: turn the Basket session's pinned list (pinned-list-17nov.json) into the compact data/basket-pilot-list.json the page uses.

  python docs/release/make_basket_pilot_list.py PINNED_LIST.json [--out data/basket-pilot-list.json]

The list changes only when a person re-pins an item (the page's method text says so). Item numbers `n` are permanent: never reused or
renumbered; a new item takes the next number, a retired item keeps its number (list "retired"). Display names are ours: the pinned
list has only slot ids. No network.
"""
import argparse
import json
import re
import sys

GROUPS = [('dairy-eggs', 'Dairy and eggs'), ('bakery', 'Bakery'), ('meat', 'Meat'), ('fish', 'Fish'), ('fruit-veg', 'Fruit and vegetables'),
          ('cupboard', 'Cupboard'), ('frozen', 'Frozen'), ('drinks', 'Drinks'), ('household', 'Household'), ('personal-care', 'Personal care')]
NAMES = {
    'milk-semi-2l': 'Semi-skimmed milk, 2 litres', 'milk-whole-2l': 'Whole milk, 2 litres', 'milk-skimmed-2l': 'Skimmed milk, 2 litres',
    'butter-salted-250g': 'Salted butter, 250 g', 'cheddar-mature-400g': 'Mature cheddar, 400 g', 'cream-double-300ml': 'Double cream, 300 ml',
    'yogurt-natural-500g': 'Natural yogurt, 500 g', 'yogurt-greek-500g': 'Greek-style yogurt, 500 g', 'bread-white-800g': 'White sliced bread, 800 g',
    'bread-wholemeal-800g': 'Wholemeal sliced bread, 800 g', 'tortilla-wraps-8': 'Tortilla wraps, pack of 8', 'crumpets-6': 'Crumpets, pack of 6',
    'pitta-6': 'Pitta breads, pack of 6', 'chicken-breast-fillets-1kg': 'Chicken breast fillets, 1 kg', 'chicken-thighs-1kg': 'Chicken thighs, 1 kg',
    'whole-chicken-1.6kg': 'Whole chicken, about 1.6 kg', 'mince-beef-lean-500g': 'Lean beef mince, 500 g', 'sausages-pork-8': 'Pork sausages, pack of 8',
    'bacon-back-300g': 'Back bacon, 300 g', 'ham-wafer-thin-120g': 'Wafer-thin ham, 120 g', 'mince-lamb-500g': 'Lamb mince, 500 g',
    'mince-turkey-500g': 'Turkey mince, 500 g', 'pork-loin-steaks-500g': 'Pork loin steaks, 500 g', 'salmon-fillets-240g': 'Salmon fillets, 240 g',
    'cod-fillets-240g': 'Cod fillets, 240 g', 'smoked-salmon-100g': 'Smoked salmon, 100 g', 'fish-fingers-10': 'Fish fingers, pack of 10',
    'bananas-5': 'Bananas, pack of 5', 'apples-gala-6': 'Gala apples, pack of 6', 'easy-peelers-600g': 'Easy peelers, 600 g', 'lemons-4': 'Lemons, pack of 4',
    'carrots-1kg': 'Carrots, 1 kg', 'onions-brown-1kg': 'Brown onions, 1 kg', 'broccoli-350g': 'Broccoli, 350 g', 'cucumber-1': 'Cucumber, one',
    'tomatoes-salad-6': 'Salad tomatoes, pack of 6', 'peppers-3': 'Peppers, pack of 3', 'mushrooms-closed-cup-250g': 'Closed cup mushrooms, 250 g',
    'spinach-baby-200g': 'Baby spinach, 200 g', 'grapes-seedless-500g': 'Seedless grapes, 500 g', 'blueberries-150g': 'Blueberries, 150 g',
    'spaghetti-500g': 'Spaghetti, 500 g', 'penne-500g': 'Penne, 500 g', 'fusilli-500g': 'Fusilli, 500 g', 'rice-basmati-1kg': 'Basmati rice, 1 kg',
    'rice-long-grain-1kg': 'Long grain rice, 1 kg', 'baked-beans-400g': 'Baked beans, 400 g', 'tomatoes-chopped-400g': 'Chopped tomatoes, 400 g',
    'sweetcorn-tin-340g': 'Sweetcorn, tin of 340 g', 'kidney-beans-400g': 'Red kidney beans, 400 g', 'chickpeas-400g': 'Chickpeas, 400 g',
    'tomato-ketchup-460g': 'Tomato ketchup, 460 g', 'mayonnaise-400g': 'Mayonnaise, 400 g', 'flour-plain-1.5kg': 'Plain flour, 1.5 kg',
    'sugar-granulated-1kg': 'Granulated sugar, 1 kg', 'sunflower-oil-1l': 'Sunflower oil, 1 litre', 'olive-oil-500ml': 'Olive oil, 500 ml',
    'porridge-oats-1kg': 'Porridge oats, 1 kg', 'cornflakes-500g': 'Cornflakes, 500 g', 'bran-flakes-500g': 'Bran flakes, 500 g', 'tea-bags-80': 'Tea bags, pack of 80',
    'coffee-instant-100g': 'Instant coffee, 100 g', 'honey-clear-340g': 'Clear honey, 340 g', 'peanut-butter-340g': 'Peanut butter, 340 g',
    'stock-cubes-chicken-12': 'Chicken stock cubes, pack of 12', 'soup-tomato-400g': 'Tomato soup, 400 g', 'digestive-biscuits-400g': 'Digestive biscuits, 400 g',
    'orange-juice-1l': 'Orange juice, 1 litre', 'apple-juice-1l': 'Apple juice, 1 litre', 'cola-2l': 'Cola, 2 litres', 'lemonade-2l': 'Lemonade, 2 litres',
    'water-still-6x2l': 'Still water, 6 x 2 litres', 'peas-frozen-900g': 'Frozen peas, 900 g', 'oven-chips-1.5kg': 'Oven chips, 1.5 kg',
    'ice-cream-vanilla-1l': 'Vanilla ice cream, 1 litre', 'pizza-margherita-350g': 'Margherita pizza, about 350 g', 'toilet-roll-9': 'Toilet roll, pack of 9',
    'kitchen-roll-2': 'Kitchen roll, pack of 2', 'washing-up-liquid-500ml': 'Washing-up liquid, 500 ml', 'laundry-liquid-1.5l': 'Laundry liquid, 1.5 litres',
    'bin-bags-20': 'Bin bags, pack of 20', 'dishwasher-tabs-30': 'Dishwasher tablets, pack of 30', 'bleach-thick-750ml': 'Thick bleach, 750 ml',
    'fabric-conditioner-1.5l': 'Fabric conditioner, 1.5 litres', 'toothpaste-75ml': 'Toothpaste, 75 ml', 'shampoo-400ml': 'Shampoo, 400 ml',
    'deodorant-spray-150ml': 'Deodorant spray, 150 ml', 'hand-wash-250ml': 'Hand wash, 250 ml', 'baby-wipes-72': 'Baby wipes, pack of 72',
    'eggs-free-range-12': 'Free-range eggs, 12', 'eggs-free-range-6': 'Free-range eggs, 6', 'mince-beef-20pct-500g': 'Beef mince, 20% fat, 500 g',
    'tuna-chunks-brine-4x145g': 'Tuna chunks in brine, 4 x 145 g', 'jam-strawberry-454g': 'Strawberry jam, 454 g', 'bacon-streaky-300g': 'Streaky bacon, 300 g',
    'potatoes-white-2kg': 'White potatoes, 2 kg', 'avocado-single': 'Avocado, one', 'bolognese-sauce-500g': 'Bolognese sauce, about 500 g',
}


def label(q):
    """(code, extra) from the Basket session's quality text. s same product, o comparable own-label, v value-range own-label,
    d pack size differs (extra = percent), u product line unconfirmed (held, not counted)."""
    if q.startswith('same product'):
        return 's', None
    if q.startswith('same brand and size only'):
        return 'u', None
    m = re.search(r'pack size differs (\d+)%', q)
    if m:
        return 'd', int(m.group(1))
    if 'value-range' in q:
        return 'v', None
    if q.startswith('comparable own-label'):
        return 'o', None
    raise SystemExit(f'unknown quality label: {q!r}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pinned')
    ap.add_argument('--out', default='data/basket-pilot-list.json')
    a = ap.parse_args()
    src = json.load(open(a.pinned, encoding='utf-8'))
    order = {g: i for i, (g, _) in enumerate(GROUPS)}
    missing = [i['slot'] for i in src if i['slot'] not in NAMES]
    if missing:
        raise SystemExit(f'no display name for: {missing}')
    items = []
    for n, it in enumerate(src):
        cells = {}
        for c in it['cells']:
            code, extra = label(c['quality'])
            cell = {'id': str(c['id']), 'name': c['name'], 'pack': c.get('pack') or '', 'url': c['url'], 'q': code}
            if extra:
                cell['d'] = extra
            if c.get('size_value') and c.get('size_unit') in ('g', 'ml', 'ea'):
                cell['sz'] = c['size_value']
                cell['su'] = c['size_unit']
            cells[c['shop']] = cell
        items.append({'n': n, 'id': it['slot'], 'g': it['category'], 'name': NAMES[it['slot']], 'kind': 's' if it['variant'] == 'same product' else 'o', 'cells': cells})
    items.sort(key=lambda x: (order[x['g']], x['n']))
    out = {'schema': 1, 'version': '2026-11-17',
           'groups': [{'id': g, 'name': n} for g, n in GROUPS],
           'shops': ['aldi', 'asda', 'sainsburys', 'tesco'],
           'checkedOn': '2026-11-17', 'checkedOnSource': 'Orchestrator message 08:15Z 17 Nov 2026: Russell approved the quality read; the record itself was not seen by the Data Website session',
           'statements': {'storeSetting': True, 'dailyRead': False},   # page sentences held back until a person confirms them (see build-basket-page.js)
           'removedShops': [],   # a shop named here is taken off the page (docs/release/basket-remove-shop.js sets it)
           'retired': [], 'items': items}
    with open(a.out, 'w', encoding='utf-8', newline='') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
        f.write('\n')
    print(f'{len(items)} items, {sum(len(i["cells"]) for i in items)} cells -> {a.out}')


if __name__ == '__main__':
    sys.exit(main())
