"""Item master for the demo ERP: Corvane Steel Works (fictional).

(sku, description, category, uom, list_price)
"""

COMPANY = {
    "name": "Corvane Steel Works",
    "street": "400 Foundry Way",
    "city": "Dayton",
    "state": "OH",
    "zip": "45402",
    "email": "orders@corvane.example",
}

ITEMS = [
    # Carts
    ("CT-2000", "Industrial Flatbed Cart, 2000 lb", "Carts", "EA", 1685.00),
    ("CT-1200", "Heavy-Duty Platform Truck Cart, 1200 lb", "Carts", "EA", 1240.00),
    ("CT-0800", "Utility Platform Cart, 800 lb", "Carts", "EA", 895.00),
    ("CT-0500", "Steel Mesh Utility Cart, 500 lb", "Carts", "EA", 410.00),
    ("CT-0350", "Folding Hand Cart, 350 lb", "Carts", "EA", 345.00),
    ("CT-TUB", "Tilt Bin Cart, 12 cu ft", "Carts", "EA", 560.00),
    ("CT-SRV", "Two-Shelf Service Cart", "Carts", "EA", 289.00),
    ("CT-DRM", "Drum Dolly, 1000 lb", "Carts", "EA", 215.00),
    ("AC-CAST4", "Replacement Caster Set, 4 pack", "Carts", "PK", 78.00),
    # Shelving
    ("SH-8448", "Wide-Span Shelving Unit 84x48x24, 5 shelf", "Shelving", "EA", 449.00),
    ("SH-7248", "Boltless Steel Shelving Unit 72x48x24, 5 shelf", "Shelving", "EA", 318.00),
    ("SH-6036", "Boltless Steel Shelving Unit 60x36x18, 4 shelf", "Shelving", "EA", 189.50),
    ("SH-WIRE", "Chrome Wire Shelving Unit 72x36x18, 4 shelf", "Shelving", "EA", 164.25),
    ("SH-ADD", "Add-On Shelving Unit 72x48x24", "Shelving", "EA", 242.00),
    ("SH-CAB", "Steel Storage Cabinet 78x36x24", "Shelving", "EA", 512.00),
    ("SH-RACK", "Pallet Rack Starter Bay, 96 in", "Shelving", "SET", 735.00),
    # Workbenches
    ("WB-ADJ", "Height-Adjustable Workbench 72x30", "Workbenches", "EA", 1475.00),
    ("WB-7236H", "Heavy-Duty Workbench 72x36 with Drawers", "Workbenches", "EA", 1135.00),
    ("WB-ESD", "ESD Safe Workbench 60x30", "Workbenches", "EA", 960.00),
    ("WB-7236", "Steel Workbench 72x36, Hardwood Top", "Workbenches", "EA", 790.00),
    ("WB-6030", "Steel Workbench 60x30, Hardwood Top", "Workbenches", "EA", 685.00),
    ("WB-4824", "Compact Workbench 48x24", "Workbenches", "EA", 455.00),
    ("WB-DRW", "Under-Bench Drawer Unit", "Workbenches", "EA", 238.00),
    ("WB-PEG", "Pegboard Back Panel, 60 in", "Workbenches", "EA", 98.00),
    ("WB-LGT", "LED Work Light Kit", "Workbenches", "EA", 64.50),
]

PRICES = {sku: price for sku, _d, _c, _u, price in ITEMS}
DESCRIPTIONS = {sku: desc for sku, desc, _c, _u, _p in ITEMS}
UOMS = {sku: uom for sku, _d, _c, uom, _p in ITEMS}
