"""Tema base QSS para la nueva GUI Qt."""

from config import tema as tk_theme


def build_qss() -> str:
    """Devuelve el stylesheet global de la app Qt.

    Se basa en los mismos tokens del tema actual para mantener coherencia visual
    durante la migracion.
    """

    return f"""
    QWidget {{
        background-color: #0F141A;
        color: #E9ECEF;
        font-family: 'Hanken Grotesk', 'Segoe UI', sans-serif;
        font-size: {tk_theme.FONT_SIZE_MD}px;
    }}

    QMainWindow {{
        background-color: #0F141A;
    }}

    QFrame#Sidebar {{
        background-color: #17232D;
        border-right: 1px solid #252E3A;
    }}

    QFrame#ContentTopBar {{
        background-color: #131820;
        border-bottom: 1px solid #252E3A;
    }}

    QWidget#TabsCorner {{
        background: transparent;
    }}

    QTabWidget::right-corner {{
        background: transparent;
        border: none;
        margin: 0px;
        padding: 0px;
    }}

    QTabWidget::left-corner {{
        background: transparent;
        border: none;
        margin: 0px;
        padding: 0px;
    }}

    QLabel#BrandTitle {{
        color: #E9ECEF;
        font-size: {tk_theme.FONT_SIZE_LG + 1}px;
        letter-spacing: 0.06em;
        font-weight: 700;
        background-color: transparent;
    }}

    QLabel#BrandSubtitle {{
        color: #8B939D;
        font-size: {tk_theme.FONT_SIZE_SM}px;
        background-color: transparent;
    }}

    QPushButton#PrimaryAction {{
        background-color: #35D18A;
        color: #062014;
        border: none;
        border-radius: 9px;
        padding: 10px 14px;
        font-weight: 700;
    }}

    QPushButton#PrimaryAction:hover {{
        background-color: #4DE89A;
    }}

    QFrame#FlowCard {{
        background-color: #161B24;
        border: 1px solid #252F3A;
        border-radius: 11px;
    }}

    QLabel#FlowTitle {{
        color: #7A8696;
        font-size: {tk_theme.FONT_SIZE_SM}px;
        letter-spacing: 0.08em;
        font-weight: 700;
        background-color: transparent;
    }}

    QLabel#FlowDotOn {{
        color: #35C98A;
        font-size: {tk_theme.FONT_SIZE_SM + 4}px;
        font-weight: 700;
        background-color: transparent;
    }}

    QLabel#FlowDotOff {{
        color: #4B5663;
        font-size: {tk_theme.FONT_SIZE_SM + 4}px;
        font-weight: 700;
        background-color: transparent;
    }}

    QLabel#FlowLabelOn {{
        color: #DCE4EB;
        font-size: {tk_theme.FONT_SIZE_SM + 1}px;
        font-weight: 600;
        background-color: transparent;
    }}

    QLabel#FlowLabelOff {{
        color: #8B939D;
        font-size: {tk_theme.FONT_SIZE_SM + 1}px;
        font-weight: 500;
        background-color: transparent;
    }}

    QLabel#FlowCountOn {{
        color: #35C98A;
        background: #173226;
        border: 1px solid #2B7A58;
        border-radius: 8px;
        padding: 1px 7px;
        font-size: {tk_theme.FONT_SIZE_SM}px;
        font-weight: 700;
        min-width: 26px;
    }}

    QLabel#FlowCountOff {{
        color: #8B939D;
        background: #232A33;
        border: 1px solid #313A45;
        border-radius: 8px;
        padding: 1px 7px;
        font-size: {tk_theme.FONT_SIZE_SM}px;
        font-weight: 600;
        min-width: 26px;
    }}

    QLabel#TopState {{
        color: #8B939D;
        background: #232A33;
        border: 1px solid #313A45;
        border-radius: 8px;
        padding: 4px 10px;
        font-size: {tk_theme.FONT_SIZE_SM}px;
        font-weight: 600;
    }}

    QLabel#TopClock {{
        color: #DCE4EB;
        background: #1A1F26;
        border: 1px solid #2B333D;
        border-radius: 8px;
        padding: 4px 10px;
        font-size: {tk_theme.FONT_SIZE_SM}px;
        font-weight: 600;
    }}

    QPushButton#PlaybackButton {{
        background-color: #1F2A35;
        border: 1px solid #3B4756;
        border-radius: 7px;
        color: #CFD5DC;
        min-height: 30px;
        min-width: 0px;
        padding: 2px 2px;
        font-weight: 600;
        outline: none;
    }}

    QPushButton#PlaybackButton:focus {{
        border: 1px solid #3B4756;
        outline: none;
    }}

    QPushButton#PlaybackButton:hover {{
        background-color: #2A3644;
        border: 1px solid #4A5A6D;
    }}

    QPushButton#PlaybackButton:checked {{
        background-color: #E8A13A33;
        color: #E8A13A;
        border-color: #E8A13A;
    }}

    QPushButton#PlaybackPlayButton {{
        background-color: #E8A13A;
        border: 1px solid #E8A13A;
        border-radius: 7px;
        color: #12161B;
        min-height: 30px;
        min-width: 0px;
        padding: 2px 4px;
        font-weight: 700;
        outline: none;
    }}

    QPushButton#PlaybackPlayButton:focus {{
        border: 1px solid #E8A13A;
        outline: none;
    }}

    QPushButton#PlaybackPlayButton:hover {{
        background-color: #F2B14E;
        border: 1px solid #F2B14E;
    }}

    QPushButton#PlaybackPlayButton:checked {{
        background-color: #E8A13A;
        border: 1px solid #E8A13A;
        color: #12161B;
    }}

    QPushButton#PlaybackSpeedButton {{
        background-color: #1F2A35;
        border: 1px solid #3B4756;
        border-radius: 7px;
        color: #9FB0BD;
        min-height: 23px;
        min-width: 0px;
        padding: 1px 2px;
        font-size: {tk_theme.FONT_SIZE_SM}px;
        font-weight: 600;
        outline: none;
    }}

    QPushButton#PlaybackSpeedButton:focus {{
        outline: none;
    }}

    QPushButton#PlaybackSpeedButton:hover {{
        background-color: #2A3644;
        border: 1px solid #4A5A6D;
        color: #C7D3DD;
    }}

    QPushButton#PlaybackSpeedButton:checked {{
        background-color: #E8A13A33;
        border: 1px solid #E8A13A;
        color: #E8A13A;
    }}

    QPushButton#ConfigInlineButton {{
        background-color: transparent;
        border: 1px solid #3A4656;
        border-radius: 7px;
        color: #CFD5DC;
        padding: 3px 8px;
        min-height: 24px;
    }}

    QPushButton#ConfigInlineButton:hover {{
        background-color: #2A3340;
        border-color: #4A5563;
        color: #E9ECEF;
    }}

    QLineEdit#ConfigCellInput {{
        background: transparent;
        border: none;
        border-radius: 0px;
        padding: 2px 4px;
        color: #E9ECEF;
        min-height: 24px;
        selection-background-color: #2563EB;
        selection-color: #FFFFFF;
    }}

    QComboBox#ConfigCellCombo {{
        background: transparent;
        border: none;
        border-radius: 0px;
        padding: 2px 4px;
        color: #E9ECEF;
        min-height: 24px;
    }}

    QComboBox#ConfigCellCombo::drop-down {{
        border: none;
        width: 18px;
    }}

    QPushButton#ConfigTurnosButton {{
        background: transparent;
        border: none;
        border-radius: 0px;
        color: #CFD5DC;
        padding: 0px;
        min-height: 20px;
        min-width: 20px;
    }}

    QPushButton#ConfigTurnosButton:hover {{
        background: #FFFFFF14;
        border-radius: 5px;
    }}

    QPushButton#ConfigDeleteButton {{
        background: transparent;
        border: none;
        color: #F56B6B;
        font-size: {tk_theme.FONT_SIZE_MD + 2}px;
        font-weight: 700;
        min-height: 22px;
        min-width: 22px;
        padding: 0px;
    }}

    QPushButton#ConfigDeleteButton:hover {{
        background: #F56B6B22;
        border-radius: 6px;
        color: #FF8E8E;
    }}

    QTabWidget::pane {{
        border: none;
        border-radius: 0px;
        background: #0F141A;
        top: 0px;
    }}

    QTabBar::tab {{
        background: transparent;
        color: #8B939D;
        border: none;
        padding: 7px 12px;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        margin-right: 3px;
        font-weight: 600;
    }}

    QTabBar::tab:hover {{
        color: #A8B2BA;
    }}

    QTabBar::tab:selected {{
        background: #E8A13A2A;
        color: #E8A13A;
        border: none;
    }}

    QFrame#Card {{
        background-color: #141A25;
        border: 1px solid #232E3A;
        border-radius: 12px;
    }}

    QFrame#CardTransparent {{
        background: transparent;
        border: none;
    }}

    QFrame#CardSoft {{
        background-color: #1A2230;
        border: 1px solid #2B3645;
        border-radius: 12px;
    }}

    QFrame#GenKpiCard {{
        background: #1a1f26;
        border: 1px solid #2b333d;
        border-radius: 12px;
    }}

    QLabel#GenKpiKey {{
        font-size: 10px;
        letter-spacing: 0.05em;
        font-weight: 700;
        color: #7a8696;
        background: transparent;
    }}

    QLabel#GenKpiVal {{
        font-family: 'IBM Plex Mono', 'Consolas', monospace;
        font-size: 18px;
        font-weight: 600;
        color: #e9ecef;
        background: transparent;
    }}

    QWidget#GenScrollContent {{
        background: transparent;
        border: none;
    }}

    QTableWidget#GenPreviewTable {{
        background: transparent;
        border: 1px solid #2B3645;
        border-radius: 8px;
        gridline-color: #2b333d;
    }}

    QTableWidget#GenPreviewTable::item {{
        padding: 6px 8px;
        color: #e9ecef;
        background: transparent;
        border-bottom: 1px solid #2b333d;
    }}

    QTableWidget#GenPreviewTable::item:selected {{
        background: #2b333d;
        color: #35d18a;
    }}

    QTableWidget#GenPreviewTable QHeaderView::section {{
        background: #171d26;
        color: #8b939d;
        border: none;
        border-bottom: 1px solid #2b333d;
        padding: 6px 8px;
        font-size: {tk_theme.FONT_SIZE_SM}px;
        font-weight: 700;
    }}

    QTableWidget#GenChangesTable {{
        background: transparent;
        gridline-color: #2b333d;
        border: none;
    }}

    QTableWidget#GenChangesTable::item {{
        padding: 8px;
        color: #e9ecef;
        background: transparent;
        border-bottom: 1px solid #2b333d;
    }}

    QTableWidget#GenChangesTable::item:selected {{
        background: #2b333d;
        color: #35d18a;
    }}

    QTableWidget#GenChangesTable QHeaderView::section {{
        background: #1a1f26;
        color: #9aa3b2;
        padding: 8px;
        border-bottom: 1px solid #2b333d;
        font-weight: 700;
        font-size: 10px;
    }}

    QLabel {{
        background: transparent;
    }}

    QLabel#SectionTitle {{
        color: #E9ECEF;
        font-family: 'Space Grotesk', 'Hanken Grotesk', sans-serif;
        font-size: {tk_theme.FONT_SIZE_MD}px;
        letter-spacing: 0.04em;
        font-weight: 700;
        background-color: transparent;
    }}

    QLabel#BoardHeader {{
        color: #8E98A3;
        font-size: {tk_theme.FONT_SIZE_SM}px;
        letter-spacing: 0.08em;
        background-color: transparent;
        font-weight: 700;
    }}

    QLabel#StockBoardHeader {{
        color: #35C98A;
        font-size: {tk_theme.FONT_SIZE_SM}px;
        letter-spacing: 0.08em;
        background-color: transparent;
        font-weight: 700;
    }}

    QLabel#CardTitle {{
        color: #e8a13a;
        font-size: {tk_theme.FONT_SIZE_MD}px;
        font-weight: 700;
        background-color: transparent;
        letter-spacing: 0.04em;
    }}

    QLabel#Muted {{
        background-color: transparent;
        color: #86909B;
    }}

    QFrame#DashboardCard {{
        background-color: {tk_theme.DASH_CARD_BG};
        border: 1px solid {tk_theme.DASH_CARD_BORDER};
        border-radius: 12px;
    }}

    QLabel#DashboardCardTitle {{
        color: {tk_theme.DASH_TITLE};
        font-size: {tk_theme.FONT_SIZE_LG}px;
        font-weight: 700;
        letter-spacing: 0.04em;
        background-color: transparent;
    }}

    QLabel#DashboardLegend {{
        color: {tk_theme.DASH_LEGEND_TEXT};
        font-size: {tk_theme.FONT_SIZE_SM}px;
        background-color: transparent;
    }}

    QLabel#DashboardBanner {{
        color: {tk_theme.FG2};
        font-size: {tk_theme.FONT_SIZE_XL}px;
        font-weight: 700;
        background-color: transparent;
    }}

    QLabel#CoherenceStatus {{
        background: transparent;
        color: #86909B;
    }}

    QLabel#CoherenceStatus[state="ok"] {{
        color: #35d18a;
    }}

    QLabel#CoherenceStatus[state="error"] {{
        color: #f56b6b;
    }}

    QFrame#ConfigHintBox {{
        background-color: #111823;
        border: 1px solid #2B3645;
        border-radius: 10px;
    }}

    QTableWidget#ConfigTable {{
        background: #11151A;
        border: 1px solid #313A45;
        border-radius: 8px;
        gridline-color: #2b333d;
    }}

    QTableWidget#ConfigTable::item {{
        padding: 6px 8px;
        color: #e9ecef;
        border-bottom: 1px solid #2b333d;
    }}

    QTableWidget#ConfigTable::item:selected {{
        background: #2b333d;
        color: #35d18a;
    }}

    QTableWidget#ConfigTable QHeaderView::section {{
        background: #171d26;
        color: #8b939d;
        border: none;
        border-bottom: 1px solid #2b333d;
        padding: 7px 8px;
        font-size: {tk_theme.FONT_SIZE_SM}px;
        font-weight: 700;
        letter-spacing: 0.04em;
    }}

    QFormLayout > QLabel {{
        color: #8b939d;
        font-size: {tk_theme.FONT_SIZE_SM + 1}px;
    }}

    QLabel#InventoryMeta {{
        color: #6D7985;
        background-color: transparent;
        font-size: {tk_theme.FONT_SIZE_SM}px;
        font-family: 'JetBrains Mono', 'Consolas', monospace;
    }}

    QFrame#InventoryShell {{
        background-color: #111923;
        border: 1px solid #233241;
        border-radius: 12px;
    }}

    QTableWidget#InventoryTable QScrollBar:vertical {{
        background: #11161D;
        width: 10px;
        margin: 4px 4px 4px 0px;
        border-radius: 5px;
    }}

    QTableWidget#InventoryTable QScrollBar::handle:vertical {{
        background: #425261;
        min-height: 28px;
        border-radius: 5px;
    }}

    QTableWidget#InventoryTable QScrollBar::handle:vertical:hover {{
        background: #526576;
    }}

    QTableWidget#InventoryTable QScrollBar::add-line:vertical,
    QTableWidget#InventoryTable QScrollBar::sub-line:vertical,
    QTableWidget#InventoryTable QScrollBar::add-page:vertical,
    QTableWidget#InventoryTable QScrollBar::sub-page:vertical {{
        background: transparent;
        border: none;
        height: 0px;
    }}

    /* === Scrollbars globales (reutiliza el look del inventario) === */
    QScrollBar:vertical {{
        background: #11161D;
        width: 10px;
        margin: 4px 4px 4px 0px;
        border-radius: 5px;
    }}

    QScrollBar::handle:vertical {{
        background: #425261;
        min-height: 28px;
        border-radius: 5px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: #526576;
    }}

    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {{
        background: transparent;
        border: none;
        height: 0px;
    }}

    QScrollBar:horizontal {{
        background: #11161D;
        height: 10px;
        margin: 0px 4px 4px 4px;
        border-radius: 5px;
    }}

    QScrollBar::handle:horizontal {{
        background: #425261;
        min-width: 28px;
        border-radius: 5px;
    }}

    QScrollBar::handle:horizontal:hover {{
        background: #526576;
    }}

    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal,
    QScrollBar::add-page:horizontal,
    QScrollBar::sub-page:horizontal {{
        background: transparent;
        border: none;
        width: 0px;
    }}

    QLabel#InventoryIdLabel {{
        color: #F0F4F8;
        font-weight: 700;
        background: transparent;
    }}

    QCalendarWidget {{
        background: #12161B;
        color: #E9ECEF;
        border: 1px solid #2A3749;
        border-radius: 8px;
    }}

    QCalendarWidget QToolButton {{
        background: #1a1f26;
        color: #E9ECEF;
        border: none;
        border-radius: 4px;
        padding: 4px;
    }}

    QCalendarWidget QToolButton:hover {{
        background: #2b333d;
    }}

    QCalendarWidget QAbstractItemView {{
        background: #16191d;
        color: #E9ECEF;
        selection-background-color: #35D18A;
        border: none;
    }}

    QCalendarWidget QMenu {{
        background: #1a1f26;
        color: #E9ECEF;
        border: 1px solid #2A3749;
    }}

    QCalendarWidget QMenu::item:selected {{
        background: #35D18A;
    }}

    QFrame#InventoryAccent {{
        border-radius: 1px;
        background: #46515E;
    }}

    QFrame#InventoryAccent[state="Trabajando"] {{
        background: #4E87C9;
    }}

    QFrame#InventoryAccent[state="CRC"] {{
        background: #C89346;
    }}

    QFrame#InventoryAccent[state="Rectificando"] {{
        background: #8A6CB5;
    }}

    QFrame#InventoryAccent[state="A rectificar"] {{
        background: #B85F70;
    }}

    QFrame#InventoryAccent[state="Enfriando"] {{
        background: #53A8B8;
    }}

    QFrame#InventoryAccent[state="Disponible"] {{
        background: #449B73;
    }}

    QFrame#InventoryAccent[state="Baja"] {{
        background: #6D7782;
    }}

    QPushButton#InventoryToolbarButton {{
        background-color: #232B37;
        color: #CFD5DC;
        border: 1px solid #3A4452;
        border-radius: 8px;
        padding: 5px 11px;
        font-size: {tk_theme.FONT_SIZE_SM}px;
        font-weight: 600;
        min-height: 28px;
    }}

    QPushButton#InventoryToolbarButton:hover {{
        background-color: #2D3545;
        border-color: #4A5563;
    }}

    QLabel#InventoryStateBadge {{
        padding: 2px 6px;
        border-radius: 8px;
        font-size: 8px;
        font-weight: 700;
        min-width: 54px;
        min-height: 20px;
        max-height: 20px;
    }}

    QLabel#InventoryStateBadge[state="Trabajando"] {{
        color: #6AB2FF;
        background: #0F2946;
        border: 1px solid #2F6CB4;
    }}

    QLabel#InventoryStateBadge[state="CRC"] {{
        color: #F0B14A;
        background: #352911;
        border: 1px solid #9B6A1F;
    }}

    QLabel#InventoryStateBadge[state="Rectificando"] {{
        color: #C69BFF;
        background: #2D1E44;
        border: 1px solid #7B56B8;
    }}

    QLabel#InventoryStateBadge[state="A rectificar"] {{
        color: #FF8E8E;
        background: #3A1E26;
        border: 1px solid #B65267;
    }}

    QLabel#InventoryStateBadge[state="Enfriando"] {{
        color: #53D9E5;
        background: #14343A;
        border: 1px solid #2798A6;
    }}

    QLabel#InventoryStateBadge[state="Disponible"] {{
        color: #48D18E;
        background: #132F25;
        border: 1px solid #2C8D61;
    }}

    QLabel#InventoryStateBadge[state="Baja"] {{
        color: #96A0AB;
        background: #232A33;
        border: 1px solid #46515E;
    }}

    QFrame#LaneBox {{
        background-color: #1A2030;
        border: 1px solid #2A3749;
        border-radius: 11px;
    }}

    QFrame#LaneBox[parada="true"] {{
        border: 2px solid #E74C3C;
        background-color: #1A2030A0;
    }}

    QWidget#LaneCanvas {{
        background: transparent;
        border: none;
    }}

    QLabel#LaneTitle {{
        color: #E9ECEF;
        background-color: transparent;
        font-size: {tk_theme.FONT_SIZE_MD}px;
        font-weight: 700;
    }}

    QLabel#LaneTitleWork {{
        color: #4BA5FF;
        background-color: transparent;
        font-size: {tk_theme.FONT_SIZE_MD}px;
        font-weight: 700;
    }}

    QLabel#LaneTitleCRC {{
        color: #F5A834;
        background-color: transparent;
        font-size: {tk_theme.FONT_SIZE_MD}px;
        font-weight: 700;
    }}

    QLabel#LaneTitleQueue {{
        color: #FF7373;
        background-color: transparent;
        font-size: {tk_theme.FONT_SIZE_MD}px;
        font-weight: 700;
    }}

    QLabel#LaneTitleCooling {{
        color: #34D3E0;
        background-color: transparent;
        font-size: {tk_theme.FONT_SIZE_MD}px;
        font-weight: 700;
    }}

    QFrame#Chip {{
        border-radius: 8px;
        border: none;
        min-width: 58px;
        min-height: 38px;
    }}

    QFrame#Chip[role="default"] {{
        background-color: #1F2837;
    }}

    QFrame#Chip[role="work"] {{
        background-color: #4BA5FF;
    }}

    QFrame#Chip[role="crc"] {{
        background-color: #F5A834;
    }}

    QFrame#Chip[role="queue"] {{
        background-color: #FF7373;
    }}

    QFrame#Chip[role="queue_next"] {{
        background-color: #5AAEFF;
        border: 1px solid #5AAEFF77;
    }}

    QFrame#Chip[role="cooling"] {{
        background-color: #34D3E0;
    }}

    QLabel#ChipTitle {{
        color: #FFFFFF;
        font-size: 10px;
        font-weight: 700;
        background-color: transparent;
    }}

    QLabel#ChipBody {{
        color: #FFFFFF;
        font-size: 10px;
        background-color: transparent;
    }}

    QFrame#MachineCard {{
        background-color: #1A2030;
        border: 1px solid #2A3749;
        border-radius: 11px;
    }}

    QFrame#MachineCard[mode="busy"] {{
        border: 1px solid #B08CF5;
        background-color: #1A20308A;
    }}

    QFrame#MachineCard[mode="idle"] {{
        border: 1px solid #35C98A;
        background-color: #1A20308A;
    }}

    QFrame#MachineCard[mode="off"] {{
        border: 1px solid #E74C3C;
        background-color: #1A20308A;
    }}

    QLabel#MachineBusy {{
        color: #B08CF5;
        font-weight: 700;
        background-color: transparent;
    }}

    QLabel#MachineGood {{
        color: #35C98A;
        font-weight: 700;
        background-color: transparent;
    }}

    QLabel#MachineOff {{
        color: #E74C3C;
        font-weight: 700;
        background-color: transparent;
    }}

    QLabel#StatPill {{
        background: #1A1F26;
        border: 1px solid #2B333D;
        border-radius: 8px;
        padding: 6px 10px;
        color: #8B939D;
        font-size: {tk_theme.FONT_SIZE_SM}px;
    }}

    QLabel#StatPillAlert {{
        background: #3A1418;
        border: 1px solid #E74C3C;
        border-radius: 8px;
        padding: 6px 10px;
        color: #FF6B6B;
        font-size: {tk_theme.FONT_SIZE_SM}px;
        font-weight: 600;
    }}

    QProgressBar#MachineProgress {{
        border: 1px solid #2B333D;
        border-radius: 5px;
        background-color: #0F1419;
        min-height: 10px;
    }}

    QProgressBar#MachineProgress::chunk {{
        border-radius: 4px;
        background-color: #B08CF5;
    }}

    QFrame#StockBarCard {{
        background: transparent;
        border: none;
        border-radius: 0px;
        min-width: 96px;
    }}

    QLabel#StockValue {{
        color: #35C98A;
        background: transparent;
        font-size: {tk_theme.FONT_SIZE_MD}px;
        font-weight: 700;
    }}

    QProgressBar#StockBarProgress {{
        border: none;
        border-radius: 0px;
        background-color: transparent;
        min-height: 110px;
        min-width: 60px;
    }}

    QProgressBar#StockBarProgress::chunk {{
        border-radius: 9px;
        background-color: #35C98A;
    }}

    QSlider#PlaybackSlider {{
        background: transparent;
        border: none;
        outline: none;
    }}

    QSlider#PlaybackSlider:focus {{
        background: transparent;
        border: none;
        outline: none;
    }}

    QSlider#PlaybackSlider::groove:horizontal {{
        border: none;
        background: #2A3440;
        height: 4px;
        border-radius: 2px;
    }}

    QSlider#PlaybackSlider::handle:horizontal {{
        background: #FFFFFF;
        border: 1px solid #D8DEE4;
        width: 10px;
        height: 10px;
        margin: -4px 0;
        border-radius: 5px;
    }}

    QSlider#PlaybackSlider::sub-page:horizontal {{
        background: #2A3440;
        border-radius: 2px;
    }}

    QSlider#PlaybackSlider::add-page:horizontal {{
        background: #2A3440;
        border-radius: 2px;
    }}

    QPlainTextEdit#ConsoleView {{
        background-color: #0C0F13;
        color: #9FB0BD;
        border: 1px solid #2B333D;
        border-radius: 10px;
        padding: 8px;
        selection-background-color: #3A4654;
    }}

    QStatusBar {{
        background: #1A1F26;
        border-top: 1px solid #262D36;
    }}
    """
