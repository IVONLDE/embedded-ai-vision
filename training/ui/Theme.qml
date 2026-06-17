pragma Singleton

import QtQuick

QtObject {
    id: theme

    property string mode: "light"

    function _c(l, sm, bl, oc, ds, dk) {
        if (mode === "light")   return l
        if (mode === "seamist") return sm
        if (mode === "blue")    return bl
        if (mode === "ocean")   return oc
        if (mode === "deepsea") return ds
        return dk
    }

    //              light     seamist   blue      ocean     deepsea   dark
    readonly property color bg:        _c("#F2F4F7","#EEF0F2","#E6F0FA","#1A2F4A","#0B1625","#0B1120")
    readonly property color panel:     _c("#FFFFFF","#F8F9FA","#F2F7FD","#213E58","#112240","#162231")
    readonly property color panelAlt:  _c("#F0F2F5","#E8EBEE","#E8F0F8","#284860","#182D48","#1A2A40")
    readonly property color header:    _c("#FFFFFF","#F0F2F4","#DBEAFE","#193250","#0D1F35","#111B2B")
    readonly property color sidebar:   _c("#F8FAFC","#E4E7EA","#EFF6FF","#152838","#081420","#0F1928")
    readonly property color control:   _c("#FFFFFF","#F5F6F7","#FFFFFF","#182D48","#0C1B30","#0D1524")
    readonly property color row:       _c("#FFFFFF","#FAFBFC","#F8FAFE","#1D3550","#0D1F35","#0F1928")
    readonly property color rowAlt:    _c("#F3F6FA","#F0F2F4","#EDF3FA","#233D58","#122845","#152030")

    readonly property color primary:       _c("#1D4ED8","#1D4ED8","#2563EB","#3B82F6","#3385E0","#1D4ED8")
    readonly property color primaryHover:  _c("#2563EB","#2563EB","#3B82F6","#60A5FA","#4A9AF0","#2563EB")
    readonly property color secondary:     _c("#0F766E","#0F766E","#0891B2","#06B6D4","#00B4D8","#38BDF8")
    readonly property color text:          _c("#111827","#2D3748","#1E293B","#D0DCF0","#D8E2F0","#E8ECF2")
    readonly property color muted:         _c("#6B7280","#8899A6","#64748B","#6880A0","#6A82A6","#8899B0")
    readonly property color border:        _c("#D6DEE8","#D0D5DD","#CDE0F5","#1F3A58","#1B3252","#2D3B50")
    readonly property color hover:         _c("#E8EEF7","#E4E8EC","#DBEAFE","#1C3250","#152D4A","#233044")
    readonly property color placeholder:   _c("#9CA3AF","#A0A8B4","#8A9DB5","#507098","#4A6288","#5A6A80")

    readonly property color success:   _c("#15803D","#15803D","#15803D","#2EAA76","#2EAA76","#15803D")
    readonly property color warning:   _c("#B45309","#B45309","#B45309","#D4952A","#D4952A","#B45309")
    readonly property color danger:    _c("#DC2626","#DC2626","#DC2626","#E05555","#E05555","#DC2626")

    readonly property color cleanTag: _c("#0F766E","#0F766E","#0F766E","#3B82F6","#3385E0","#0F766E")
    readonly property color genTag:   _c("#B45309","#B45309","#B45309","#06B6D4","#00B4D8","#B45309")

    function setMode(nextMode) {
        var valid = ["light","seamist","blue","ocean","deepsea","dark"]
        if (valid.indexOf(nextMode) >= 0) mode = nextMode
    }
}
