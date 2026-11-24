"""Fixed catalogue data: sub-types per category (OQ-19) and the item field definitions the API returns.

The key-spec field lists are the MVP set (validated JSON in `items.key_specs`, ERD s5); typed columns replace
them in Sprint 3. `required` means "required to activate the item".
"""

from dataclasses import dataclass, field

SUBTYPES: dict[str, list[str]] = {
    "Laptop": [  # segment list, BE 3.3
        "Consumer",
        "Business",
        "Gaming",
        "Workstation",
        "Ultrabook",
        "Chromebook",
        "2-in-1",
        "Rugged",
    ],
    "Laptop Part": [  # part types, BE 3.4
        "Battery",
        "Charger or adapter",
        "Screen",
        "Touch digitiser or assembly",
        "Keyboard",
        "Trackpad",
        "RAM module",
        "SSD or HDD",
        "Caddy or enclosure",
        "Motherboard",
        "Processor or graphics chip",
        "Cooling fan or heatsink",
        "Casing and covers",
        "Hinges and brackets",
        "Speakers and microphones",
        "Webcam module",
        "Wi-Fi or Bluetooth card",
        "DC jack or charging port",
        "Display cable",
        "Power button or fingerprint board",
        "CMOS battery",
        "Optical drive",
        "Screws and small parts",
    ],
    "Accessory": [  # accessory types, BE 3.5
        "Bags, backpacks and sleeves",
        "Mice",
        "Keyboards",
        "Keyboard and mouse combos",
        "Headsets, headphones and earbuds",
        "Speakers and microphones",
        "Webcams",
        "Flash drives",
        "External drives",
        "Memory cards and card readers",
        "Laptop chargers",
        "Phone and USB chargers",
        "Power banks",
        "Cables",
        "Adapters, hubs and docking stations",
        "Monitors",
        "Stands, cooling pads and mounts",
        "Screen protectors and privacy filters",
        "Keyboard covers, skins and cases",
        "Surge protectors, extension leads and UPS",
        "Networking",
        "Printers and consumables",
        "Presenters, controllers and other peripherals",
        "Security locks and cleaning kits",
    ],
}


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    type: str  # text | integer | decimal | boolean | choice
    required: bool = False
    choices: list[str] = field(default_factory=list)
    group: str | None = None
    in_key_specs: bool = True


CONDITIONS = ["new", "refurbished", "used"]
GRADES = ["A", "B", "C"]

COMMON_FIELDS = [
    FieldDef("name", "Name", "text", True, group="Identity", in_key_specs=False),
    FieldDef("subtype_id", "Sub-type", "integer", True, group="Identity", in_key_specs=False),
    FieldDef("brand_id", "Brand", "integer", True, group="Identity", in_key_specs=False),
    FieldDef("model_name", "Model name", "text", True, group="Identity", in_key_specs=False),
    FieldDef("mpn", "Manufacturer part number", "text", True, group="Identity", in_key_specs=False),
    FieldDef("condition", "Condition", "choice", True, CONDITIONS, "Identity", False),
    FieldDef("grade", "Grade", "choice", False, GRADES, "Identity", False),
    FieldDef("description", "Description", "text", False, group="Details", in_key_specs=False),
    FieldDef("show_on_website", "Show on website", "boolean", False, group="Details", in_key_specs=False),
    FieldDef("search_keywords", "Search keywords", "text", False, group="Details", in_key_specs=False),
]

KEY_SPECS: dict[str, list[FieldDef]] = {
    "Laptop": [
        FieldDef("processor", "Processor", "text", True, group="Processor"),
        FieldDef("ram_gb", "RAM (GB)", "integer", True, group="Memory"),
        FieldDef("storage_gb", "Storage (GB)", "integer", True, group="Storage"),
        FieldDef(
            "storage_type", "Storage type", "choice", True, ["NVMe SSD", "SATA SSD", "HDD", "eMMC"], "Storage"
        ),
        FieldDef("screen_size_in", "Screen size (in)", "decimal", False, group="Display"),
        FieldDef("touchscreen", "Touchscreen", "boolean", False, group="Display"),
        FieldDef("os", "Operating system", "text", False, group="Software"),
        FieldDef("keyboard_layout", "Keyboard layout", "choice", False, ["US", "UK", "Other"], "Input"),
        FieldDef("colour", "Colour", "text", False, group="Physical"),
    ],
    "Laptop Part": [
        FieldDef("quality_type", "Quality type", "choice", True, ["OEM", "Compatible", "Used"], "Quality"),
        FieldDef("compatible_models", "Compatible models", "text", False, group="Compatibility"),
        FieldDef("colour", "Colour", "text", False, group="Physical"),
    ],
    "Accessory": [
        FieldDef(
            "connectivity",
            "Connectivity",
            "choice",
            False,
            ["Wired", "Bluetooth", "2.4 GHz receiver", "USB-A", "USB-C"],
            "Connection",
        ),
        FieldDef("colour", "Colour", "text", False, group="Physical"),
        FieldDef("compatibility_notes", "Compatibility notes", "text", False, group="Compatibility"),
    ],
}


def definitions_for(category_name: str) -> list[FieldDef]:
    return COMMON_FIELDS + KEY_SPECS.get(category_name, [])
