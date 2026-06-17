import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import QtMultimedia
import ".."

Item {
    id: root
    anchors.fill: parent

    readonly property color bgDark: Theme.bg
    readonly property color panelBg: Theme.panel
    readonly property color primaryColor: Theme.primary
    readonly property color textColor: Theme.text
    readonly property color textMuted: Theme.muted
    readonly property color borderColor: Theme.border
    readonly property color tableHoverBg: Theme.hover

    HelpIcon {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.topMargin: -16
        anchors.rightMargin: -16
        title: "数据管理帮助"
        body: "本页用于导入、浏览和维护数据集。\n\n1. 顶部筛选区可按数据阶段和数据类型过滤列表，也可以在搜索框输入名称关键字快速定位数据集。\n2. 点击“导入源数据集”后，填写数据集名称、选择模态类型，并选择导入文件或文件夹。文件夹导入会保留目录结构，适合图像、标签、音频等成套数据。\n3. 数据集卡片展示样本数量、数据阶段、类型和存储信息。点击卡片可进入文件明细，查看目录、文件列表和样本预览。\n4. 文件明细窗口支持进入子目录、点击返回上级目录、预览图片/文本/音频等样本内容。\n5. 数据集操作按钮可用于修改名称、查看明细或删除数据集。删除前会弹出确认框，避免误删。\n6. 导入或删除后页面会自动刷新；如果外部文件发生变化，可重新进入数据集明细确认实际文件状态。"
    }

    // ======== 状态与数据源 ========
    property var selectedDataset: null
    property var currentFileList: [] // 当前选中数据集的文件列表
    property string currentDirPath: ""   // 当前浏览的目录路径
    property var currentDirDirs: []      // 当前目录下的子文件夹
    property var currentDirFiles: []     // 当前目录下的文件

    property var allDatasets: []
    property var displayedDatasets: []
    property string currentCategory: "全部"
    property string currentStage: "raw"
    property string searchQuery: ""
    property int pendingDeleteId: -1
    property bool importing: false
    property var pendingImportArgs: null
    property var previewSample: null
    property bool samplePreviewVisible: false
    property string pendingPreviewKey: ""
    property string previewKind: ""
    property string previewText: ""
    property string previewSource: ""
    property string previewTitle: ""
    property string toastMessage: ""

    // ======== 后端信号连接 ========
    Connections {
        target: backendService
        function onDatasetsUpdated(data) {
            var items = []
            if (data && data.items) {
                items = data.items
            } else if (Array.isArray(data)) {
                items = data
            }
            // 预计算缓存字段，避免 filter / delegate 渲染时重复调用 datasetStage()
            for (var i = 0; i < items.length; i++) {
                var item = items[i]
                item._stage = root.datasetStage(item)
                item._cleanName = (item.name || "").split("|Status:")[0]
            }
            root.allDatasets = items
            root.filterData()
        }

        function onDatasetSamplesUpdated(data) {
            var files = []
            var items = data && data.items ? data.items : []
            for (var i = 0; i < items.length; i++) {
                files.push(root.sampleToFileRow(items[i]))
            }
            root.currentFileList = files
        }

        function onDatasetDirectoryUpdated(result) {
            var data = result && result.data ? result.data : {}
            root.currentDirPath = data.path || ""
            root.currentDirDirs = data.dirs || []
            var rawFiles = data.files || []
            var fileRows = []
            for (var j = 0; j < rawFiles.length; j++) {
                fileRows.push(root.sampleToFileRow(rawFiles[j]))
            }
            root.currentDirFiles = fileRows
        }

        function onSamplePreviewUpdated(data) {
            var payload = data && data.data ? data.data : data
            if (!payload) return
            var incomingKey = String(payload.sample_id || payload.id || payload.file_path || payload.relative_path || payload.name || "")
            if (root.pendingPreviewKey !== "" && incomingKey !== "" && incomingKey !== root.pendingPreviewKey) return
            if (root.samplePreviewVisible && root.previewSource !== "" && payload.file_path && root.previewSource === root.localFileUrl(payload.file_path)) return
            root.previewKind = payload.preview_kind || "file"
            root.previewText = payload.text_content || payload.error || ""
            root.previewTitle = payload.name || payload.relative_path || "样本预览"
            root.previewSource = payload.file_path ? root.localFileUrl(payload.file_path) : ""
            if (root.previewKind === "audio" && root.previewSource !== "") {
                previewPlayer.source = root.previewSource
            }
            root.samplePreviewVisible = true
            fileDetailPopup.forceActiveFocus()
        }

        function onImportStatusUpdated(message, success) {
            root.showToast(message)
        }
    }

    Component.onCompleted: {
        loadData()
    }

    function loadData() {
        backendService.getDatasets(1, 100, "")
    }

    function showToast(message) {
        root.toastMessage = message || ""
        toastMsg.open()
        toastAnim.restart()
        toastCloseTimer.restart()
    }

    function filterData() {
        var q = searchQuery.toLowerCase()
        displayedDatasets = allDatasets.filter(function(item) {
            var cleanName = item._cleanName || (item.name || "").split("|Status:")[0]
            var matchSearch = cleanName.toLowerCase().indexOf(q) !== -1
            var matchCategory = currentCategory === "全部" || item.type === currentCategory
            var matchStage = currentStage === "all" || (item._stage || datasetStage(item)) === currentStage
            return matchSearch && matchCategory && matchStage
        })
    }

    function datasetStage(item) {
        var stage = String(item && item.stage ? item.stage : "").toLowerCase()
        if (stage === "cleaned" || stage === "generated" || stage === "test") return stage
        var status = String(item && item.status ? item.status : "").toLowerCase()
        if (status === "cleaned" || status === "generated" || status === "test") return status
        var tags = item && item.tags ? item.tags : []
        for (var i = 0; i < tags.length; i++) {
            var tag = String(tags[i]).toLowerCase()
            if (tag === "cleaned" || tag === "generated" || tag === "test") return tag
        }
        var name = String(item && item.name ? item.name : "")
        if (name.indexOf("|Status:清洗文件") !== -1 || name.indexOf("清洗") !== -1) return "cleaned"
        if (name.indexOf("|Status:扩增文件") !== -1 || name.indexOf("扩增") !== -1 || name.indexOf("生成") !== -1) return "generated"
        if (stage === "raw" || status === "raw" || status === "created" || status === "imported") return "raw"
        for (var j = 0; j < tags.length; j++) {
            if (String(tags[j]).toLowerCase() === "raw") return "raw"
        }
        return "raw"
    }

    function stageLabel(item) {
        var stage = item._stage || datasetStage(item)
        if (stage === "cleaned") return "清洗数据集"
        if (stage === "generated") return "生成数据集"
        if (stage === "test") return "测试数据集"
        return "原始数据集"
    }

    // 防止后端误判非图片扩展名导致 QML 解码失败
    function isImageExtension(path) {
        var ext = String(path).toLowerCase().split('.').pop()
        return ["jpg","jpeg","png","bmp","gif","webp","tif","tiff"].indexOf(ext) >= 0
    }

    function sampleToFileRow(sample) {
        var labelTexts = []
        var rawLabels = sample.labels || sample.labels_json || []
        for (var i = 0; i < rawLabels.length; i++) {
            var l = rawLabels[i]
            if (typeof l === "string") labelTexts.push(l)
            else if (l && l.class_name) labelTexts.push(l.class_name)
        }
        var bytes = sample.size_bytes || sample.size || 0
        var sizeText = "0 B"
        if (bytes > 0) {
            if (bytes < 1024) sizeText = bytes + " B"
            else if (bytes < 1048576) sizeText = (bytes / 1024).toFixed(1) + " KB"
            else if (bytes < 1073741824) sizeText = (bytes / 1048576).toFixed(1) + " MB"
            else sizeText = (bytes / 1073741824).toFixed(2) + " GB"
        }
        var labelsText = labelTexts.length > 0 ? labelTexts.join(", ") : "-"
        return {
            sampleId: sample.id || -1,
            name: sample.name || sample.relative_path || "未命名样本",
            type: sample.type || sample.modality || sample.extension || "",
            size: sizeText,
            modified: sample.modified || sample.updated_at || "",
            previewKind: sample.preview_kind || "",
            filePath: sample.file_path || "",
            labels: labelTexts,
            _labelsText: labelsText,
            _isImage: root.isImageExtension(sample.file_path || sample.relative_path || "")
        }
    }

    function localFileUrl(path) {
        var clean = String(path || "").replace(/\\/g, "/")
        if (clean.indexOf("file://") === 0) return clean
        return "file:///" + clean
    }

    // QML 内联 URL 解码（Qt 5.15 JS 引擎无 decodeURIComponent）
    function _urlDecode(str) {
        var result = str
        result = result.replace(/%20/g, " ")
        result = result.replace(/%23/g, "#")
        result = result.replace(/%25/g, "%")
        result = result.replace(/%26/g, "&")
        result = result.replace(/%2B/g, "+")
        result = result.replace(/%2C/g, ",")
        result = result.replace(/%2F/g, "/")
        result = result.replace(/%3A/g, ":")
        result = result.replace(/%3B/g, ";")
        result = result.replace(/%3D/g, "=")
        result = result.replace(/%3F/g, "?")
        result = result.replace(/%40/g, "@")
        result = result.replace(/%5B/g, "[")
        result = result.replace(/%5D/g, "]")
        // 处理 %XX 形式的其他编码
        result = result.replace(/%([0-9A-Fa-f]{2})/g, function(match, hex) {
            return String.fromCharCode(parseInt(hex, 16))
        })
        return result
    }

    function localPathFromUrl(url) {
        var value = String(url || "")
        if (value.indexOf("file:///") === 0) {
            value = value.slice("file:///".length)
            if (!/^[A-Za-z]:\//.test(value)) {
                value = "/" + value
            }
        } else if (value.indexOf("file://") === 0) {
            value = value.slice("file://".length)
            if (!/^[A-Za-z]:\//.test(value) && value.charAt(0) !== "/") {
                value = "/" + value
            }
        }
        return root._urlDecode(value)
    }

    function datasetNameFromPath(path) {
        var clean = String(path || "").replace(/\\/g, "/")
        while (clean.length > 1 && clean.charAt(clean.length - 1) === "/") {
            clean = clean.slice(0, -1)
        }
        var parts = clean.split("/")
        return parts.length > 0 ? parts[parts.length - 1] : ""
    }

    function previewFile(file) {
        root.previewSample = file
        var previewKey = String(file ? (file.sampleId > 0 ? file.sampleId : (file.filePath || file.name || "")) : "")
        if (root.samplePreviewVisible && root.pendingPreviewKey === previewKey) return
        root.pendingPreviewKey = previewKey
        if (file && file.sampleId && file.sampleId > 0) {
            backendService.getSamplePreview(file.sampleId)
        } else if (file && file.filePath) {
            backendService.previewFileByPath(file.filePath)
        } else {
            root.previewKind = "file"
            root.previewTitle = file && file.name ? file.name : "样本预览"
            root.previewText = "该文件没有后端样本记录，无法读取真实文件内容。"
            root.previewSource = ""
            root.samplePreviewVisible = true
            fileDetailPopup.forceActiveFocus()
        }
    }

    function closeSamplePreview() {
        root.samplePreviewVisible = false
        root.pendingPreviewKey = ""
        previewPlayer.stop()
    }

    function openSamplePreview(sample) {
        previewFile(sample)
    }

    // 触发文件详情弹窗
    function enterFileDetail(dataset) {
        selectedDataset = dataset
        currentFileList = []
        currentDirPath = ""
        currentDirDirs = []
        currentDirFiles = []
        samplePreviewVisible = false
        pendingPreviewKey = ""
        if (dataset.id) {
            backendService.getDatasetDirectory(dataset.id, "")
        }
        fileDetailPopup.isMaximized = false
        fileDetailPopup.open()
    }

    function navigateToDir(dirName) {
        var newPath = currentDirPath ? currentDirPath + "/" + dirName : dirName
        backendService.getDatasetDirectory(selectedDataset.id, newPath)
    }

    function navigateToBreadcrumb(index) {
        // 根据面包屑索引构建路径
        var paths = currentDirPath ? currentDirPath.split("/") : []
        if (index < 0 || index >= paths.length) {
            // 回到根目录
            backendService.getDatasetDirectory(selectedDataset.id, "")
        } else {
            var newPath = paths.slice(0, index + 1).join("/")
            backendService.getDatasetDirectory(selectedDataset.id, newPath)
        }
    }

    // ======== 顶部操作栏 & 表格列表区 ========
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 15

        // 1. 顶部操作栏
        RowLayout {
            Layout.fillWidth: true
            spacing: 15

            Label {
                text: "数据类型:"
                font.pixelSize: 14
                font.bold: true
                color: "#4DD0E1"
            }

            StableComboBox {
                id: categoryCombo
                model: ["全部", "图像", "文本", "音频"]
                Layout.preferredWidth: 120
                background: Rectangle {
                    color: Theme.control
                    border.color: Theme.border
                    radius: 4
                }
                contentItem: Text {
                    text: categoryCombo.currentText
                    color: Theme.text
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: Text.AlignHCenter
                }
                onCurrentTextChanged: {
                    currentCategory = currentText
                    filterData()
                }
            }

            Label {
                text: "数据阶段:"
                font.pixelSize: 14
                font.bold: true
                color: "#4DD0E1"
            }

            StableComboBox {
                id: stageCombo
                model: ["全部", "原始数据集", "清洗数据集", "生成数据集", "测试数据集"]
                currentIndex: 1
                Layout.preferredWidth: 130
                background: Rectangle {
                    color: Theme.control
                    border.color: Theme.border
                    radius: 4
                }
                contentItem: Text {
                    text: stageCombo.currentText
                    color: Theme.text
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: Text.AlignHCenter
                }
                onCurrentTextChanged: {
                    if (currentText === "清洗数据集") currentStage = "cleaned"
                    else if (currentText === "生成数据集") currentStage = "generated"
                    else if (currentText === "测试数据集") currentStage = "test"
                    else if (currentText === "原始数据集") currentStage = "raw"
                    else currentStage = "all"
                    filterData()
                }
            }

            TextField {
                id: searchInput
                placeholderText: "搜索数据集..."
                placeholderTextColor: Theme.muted
                color: Theme.text
                Layout.preferredWidth: 220
                background: Rectangle {
                    color: Theme.control
                    border.color: Theme.border
                    radius: 4
                }
                // 防抖：每次输入重启 250ms 定时器，停止打字后才执行过滤
                onTextChanged: searchDebounceTimer.restart()
            }

            // 搜索防抖定时器 —— 避免每次按键都触发全量过滤+列表重建
            Timer {
                id: searchDebounceTimer
                interval: 250
                repeat: false
                onTriggered: {
                    root.searchQuery = searchInput.text
                    root.filterData()
                }
            }

            Item { Layout.fillWidth: true } // 弹性占位

            Button {
                text: "+ 导入源数据集"
                font.bold: true
                font.pixelSize: 14
                background: Rectangle {
                    color: parent.pressed ? "#0277BD" : parent.hovered ? "#0288D1" : "#039BE5"
                    radius: 4
                }
                contentItem: Text {
                    text: parent.text
                    color: "white"
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                onClicked: createDialog.open()
            }
        }

        // 2. 核心展示区 (只有数据集列表)
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.row
            border.color: Theme.border
            radius: 8
            clip: true

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                // 表头
                Rectangle {
                    Layout.fillWidth: true
                    height: 45
                    color: Theme.rowAlt
                    Rectangle {
                        anchors.fill: parent
                        color: "transparent"
                        border.color: Theme.border
                        border.width: 1
                    }
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 15
                        anchors.rightMargin: 15
                        spacing: 10

                        Label { text: "数据集名称"; font.bold: true; color: Theme.muted; Layout.preferredWidth: 200 }
                        Item { Layout.fillWidth: true } // 弹簧
                        Label { text: "类型/阶段"; font.bold: true; color: Theme.muted; Layout.preferredWidth: 140 }
                        Label { text: "文件总数"; font.bold: true; color: Theme.muted; Layout.preferredWidth: 100 }
                        Label { text: "存储占用"; font.bold: true; color: Theme.muted; Layout.preferredWidth: 100 }
                        Label { text: "操作管理"; font.bold: true; color: Theme.muted; Layout.preferredWidth: 196; horizontalAlignment: Text.AlignHCenter }
                    }
                }

                ListView {
                    id: datasetListView
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 4
                    model: displayedDatasets

                    delegate: Rectangle {
                        width: datasetListView.width
                        height: 55
                        color: Theme.panel
                        border.color: Theme.border
                        border.width: 1
                        radius: 4
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 15
                            anchors.rightMargin: 15
                            spacing: 10

                            Label {
                                text: modelData._cleanName || (modelData.name || "未命名").split("|Status:")[0]
                                color: Theme.text
                                font.pixelSize: 14
                                font.bold: true
                                Layout.preferredWidth: 200
                                elide: Text.ElideRight
                            }
                            Item { Layout.fillWidth: true } // 弹簧
                            Label { text: (modelData.type || "图像") + " / " + root.stageLabel(modelData); color: "#4DD0E1"; Layout.preferredWidth: 140; elide: Text.ElideRight }
                            Label { text: modelData.sampleCount !== undefined ? modelData.sampleCount : "0"; color: "#94A3B8"; Layout.preferredWidth: 100 }
                            Label { text: modelData.size || "0 MB"; color: "#94A3B8"; Layout.preferredWidth: 100 }

                            // 操作按钮区 (总宽度 196)
                            RowLayout {
                                Layout.preferredWidth: 196
                                spacing: 8

                                Button {
                                    text: "查看"
                                    Layout.preferredWidth: 60
                                    Layout.preferredHeight: 30
                                    background: Rectangle {
                                        color: parent.hovered ? Theme.hover : Theme.control
                                        radius: 4
                                        border.color: Theme.border
                                    }
                                    contentItem: Text {
                                        text: parent.text
                                        color: "#D1D5DB"
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                    onClicked: enterFileDetail(modelData)
                                }

                                Button {
                                    text: "修改"
                                    Layout.preferredWidth: 60
                                    Layout.preferredHeight: 30
                                    background: Rectangle {
                                        color: parent.hovered ? "#0369A1" : "#0284C7"
                                        radius: 4
                                    }
                                    contentItem: Text {
                                        text: parent.text
                                        color: "white"
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                    onClicked: {
                                        editDialog.datasetId = modelData.id
                                        editDialog.editName = (modelData.name || "").split("|Status:")[0]
                                        editDialog.editType = modelData.type
                                        editDialog.open()
                                    }
                                }

                                Button {
                                    text: "删除"
                                    Layout.preferredWidth: 60
                                    Layout.preferredHeight: 30
                                    background: Rectangle {
                                        color: parent.hovered ? "#BE123C" : "#E11D48"
                                        radius: 4
                                    }
                                    contentItem: Text {
                                        text: parent.text
                                        color: "white"
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                    onClicked: {
                                        if(modelData.id) {
                                            root.pendingDeleteId = modelData.id
                                            deleteConfirmPopup.open()
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                Text {
                    Layout.alignment: Qt.AlignCenter
                    text: "暂无匹配的源数据集"
                    color: Theme.muted
                    font.pixelSize: 16
                    visible: datasetListView.count === 0
                }
            }
        }
    }


    // ======== 3. 弹窗组件 ========

    // --- 新增：带有拖拽和放大缩小功能的文件详情弹窗 ---
    Popup {
        id: fileDetailPopup
        property bool isMaximized: false

        // 动态计算尺寸和位置，实现放大缩小
        width: isMaximized ? root.width * 0.95 : 850
        height: isMaximized ? root.height * 0.95 : 600
        x: (root.width - width) / 2
        y: (root.height - height) / 2

        modal: true
        focus: true
        closePolicy: Popup.NoAutoClose // 必须点右上角关闭

        background: Rectangle {
            color: Theme.row
            border.color: Theme.border
            border.width: 1
            radius: fileDetailPopup.isMaximized ? 0 : 8
            clip: true
        }

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            // 标题栏 (支持拖拽和按钮)
            Rectangle {
                Layout.fillWidth: true
                height: 48
                color: Theme.rowAlt

                // 拖拽逻辑
                MouseArea {
                    anchors.fill: parent
                    property point clickPos: "0,0"
                    onPressed: function(mouse) { clickPos = Qt.point(mouse.x, mouse.y) }
                    onPositionChanged: function(mouse) {
                        if (!fileDetailPopup.isMaximized) {
                            var delta = Qt.point(mouse.x - clickPos.x, mouse.y - clickPos.y)
                            fileDetailPopup.x += delta.x
                            fileDetailPopup.y += delta.y
                        }
                    }
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 20
                    anchors.rightMargin: 15
                    spacing: 10

                    Label {
                        text: "📁 管理文件: " + (selectedDataset ? selectedDataset.name.split("|Status:")[0] : "")
                        font.pixelSize: 16
                        font.bold: true
                        color: Theme.text
                    }

                    Item { Layout.fillWidth: true } // 弹簧占位

                    // 放大/缩小 按钮
                    Rectangle {
                        width: 32; height: 32; radius: 4; color: "transparent"
                        Text {
                            text: fileDetailPopup.isMaximized ? "🗗" : "🗖"
                            color: Theme.muted
                            font.pixelSize: 15
                            anchors.centerIn: parent
                        }
                        MouseArea {
                            anchors.fill: parent; hoverEnabled: true
                            onEntered: parent.color = Theme.border
                            onExited: parent.color = "transparent"
                            onClicked: fileDetailPopup.isMaximized = !fileDetailPopup.isMaximized
                        }
                    }

                    // 关闭 按钮
                    Rectangle {
                        width: 32; height: 32; radius: 4; color: "transparent"
                        Text {
                            text: "✕"
                            color: "#E11D48"
                            font.pixelSize: 16
                            font.bold: true
                            anchors.centerIn: parent
                        }
                        MouseArea {
                            anchors.fill: parent; hoverEnabled: true
                            onEntered: parent.color = "#4C1D28"
                            onExited: parent.color = "transparent"
                            onClicked: {
                                root.closeSamplePreview()
                                fileDetailPopup.close()
                            }
                        }
                    }
                }

                // 标题栏底部边框
                Rectangle { width: parent.width; height: 1; color: Theme.border; anchors.bottom: parent.bottom }
            }

            // 面包屑导航栏
            Rectangle {
                Layout.fillWidth: true
                height: 40
                color: Theme.panel

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 16
                    anchors.rightMargin: 16
                    spacing: 4

                    // 根目录按钮 (数据集名)
                    Text {
                        text: selectedDataset ? (selectedDataset.name || "数据集").split("|Status:")[0] : "数据集"
                        color: currentDirPath === "" ? Theme.text : "#93C5FD"
                        font.pixelSize: 14
                        font.bold: true
                        MouseArea {
                            anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                            onClicked: root.navigateToBreadcrumb(-1)
                        }
                    }

                    Repeater {
                        model: currentDirPath ? currentDirPath.split("/") : []
                        delegate: RowLayout {
                            spacing: 4
                            Text { text: "›"; color: "#64748B"; font.pixelSize: 14 }
                            Text {
                                text: modelData
                                color: index === currentDirPath.split("/").length - 1 ? Theme.text : "#93C5FD"
                                font.pixelSize: 14
                                font.bold: index === currentDirPath.split("/").length - 1
                                MouseArea {
                                    anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                    onClicked: root.navigateToBreadcrumb(index)
                                }
                            }
                        }
                    }

                    Item { Layout.fillWidth: true }

                    Label {
                        text: currentDirDirs.length + " 个文件夹, " + currentDirFiles.length + " 个文件"
                        color: Theme.muted
                        font.pixelSize: 12
                    }
                }
            }

            // 内容区域：文件夹 + 文件（文件列表使用 ListView 虚拟化以支持大数据量）
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: !root.samplePreviewVisible
                spacing: 0

                // ".." 返回上级 (根目录不显示)
                Rectangle {
                    id: backRow
                    visible: currentDirPath !== ""
                    Layout.fillWidth: true
                    height: 40
                    color: Theme.rowAlt
                    MouseArea {
                        anchors.fill: parent; hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onEntered: backRow.color = Theme.hover
                        onExited: backRow.color = Theme.rowAlt
                        onClicked: root.navigateToBreadcrumb(currentDirPath.split("/").length - 2)
                    }
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 16; spacing: 10
                        Text { text: "📁"; font.pixelSize: 16 }
                        Label { text: ".. 返回上级"; color: "#93C5FD"; font.pixelSize: 14; font.bold: true }
                    }
                }

                // 文件夹列表（通常数量少，Repeater 即可）
                Repeater {
                    model: currentDirDirs
                    delegate: Rectangle {
                        id: folderDelegate
                        Layout.fillWidth: true
                        height: 42
                        color: index % 2 === 0 ? Theme.rowAlt : "transparent"
                        MouseArea {
                            anchors.fill: parent; hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onEntered: folderDelegate.color = Theme.hover
                            onExited: folderDelegate.color = index % 2 === 0 ? Theme.rowAlt : "transparent"
                            onClicked: root.navigateToDir(modelData)
                        }
                        RowLayout {
                            anchors.fill: parent; anchors.leftMargin: 16; anchors.rightMargin: 16; spacing: 10
                            Text { text: "📁"; font.pixelSize: 18 }
                            Label { text: modelData; color: "#93C5FD"; font.pixelSize: 14; font.bold: true; Layout.fillWidth: true; elide: Text.ElideRight }
                            Label { text: "文件夹"; color: Theme.muted; font.pixelSize: 12 }
                        }
                    }
                }

                // 文件列表 → ListView 虚拟化，支持上千文件流畅滚动
                ListView {
                    id: fileListView
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: currentDirFiles
                    cacheBuffer: 300
                    spacing: 0
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    delegate: Rectangle {
                        width: fileListView.width
                        height: 40
                        color: index % 2 === 0 ? Theme.rowAlt : "transparent"
                        MouseArea {
                            anchors.fill: parent; hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onEntered: parent.color = Theme.hover
                            onExited: parent.color = index % 2 === 0 ? Theme.rowAlt : "transparent"
                            onClicked: root.openSamplePreview(modelData)
                        }
                        RowLayout {
                            anchors.fill: parent; anchors.leftMargin: 16; anchors.rightMargin: 16; spacing: 10
                            Text { text: "📄"; font.pixelSize: 14 }
                            Label { text: modelData.name; color: Theme.text; font.pixelSize: 13; Layout.fillWidth: true; elide: Text.ElideRight }
                            Label { text: modelData._labelsText || "-"; color: modelData.labels && modelData.labels.length > 0 ? "#4DD0E1" : Theme.muted; font.pixelSize: 12; Layout.preferredWidth: 120; elide: Text.ElideRight }
                            Label { text: modelData.type || ""; color: Theme.muted; font.pixelSize: 12; Layout.preferredWidth: 60 }
                            Label { text: modelData.size || ""; color: Theme.muted; font.pixelSize: 12; Layout.preferredWidth: 80 }
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: root.samplePreviewVisible
                color: Theme.panel
                border.color: Theme.border
                radius: 6
                clip: true

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 12

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        Label {
                            text: root.previewTitle
                            color: Theme.text
                            font.pixelSize: 15
                            font.bold: true
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                        }

                        Button {
                            text: "返回列表"
                            Layout.preferredWidth: 88
                            Layout.preferredHeight: 30
                            background: Rectangle { color: parent.hovered ? Theme.hover : Theme.control; radius: 4; border.color: Theme.border }
                            contentItem: Text { text: parent.text; color: Theme.text; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                            onClicked: root.closeSamplePreview()
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        color: Theme.row
                        border.color: Theme.border
                        radius: 6
                        clip: true

                        Image {
                            anchors.fill: parent
                            anchors.margins: 12
                            visible: root.previewKind === "image" && root.previewSource !== "" && root.isImageExtension(root.previewSource)
                            source: (root.previewKind === "image" && root.isImageExtension(root.previewSource)) ? root.previewSource : ""
                            fillMode: Image.PreserveAspectFit
                            asynchronous: true
                        }

                        ScrollView {
                            anchors.fill: parent
                            anchors.margins: 12
                            visible: root.previewKind === "text"

                            TextArea {
                                text: root.previewText
                                readOnly: true
                                wrapMode: TextEdit.Wrap
                                color: Theme.text
                                selectByMouse: true
                                background: Rectangle { color: "transparent" }
                            }
                        }

                        ColumnLayout {
                            anchors.centerIn: parent
                            width: Math.min(parent.width - 60, 520)
                            spacing: 14
                            visible: root.previewKind === "audio"

                            Text {
                                text: root.previewTitle
                                color: Theme.text
                                font.pixelSize: 15
                                font.bold: true
                                Layout.fillWidth: true
                                horizontalAlignment: Text.AlignHCenter
                                elide: Text.ElideRight
                            }

                            Text {
                                text: root.previewSource !== "" ? root.previewSource : "暂无音频路径"
                                color: Theme.muted
                                font.pixelSize: 12
                                Layout.fillWidth: true
                                horizontalAlignment: Text.AlignHCenter
                                elide: Text.ElideMiddle
                            }

                            RowLayout {
                                Layout.alignment: Qt.AlignHCenter
                                spacing: 10

                                Button {
                                    text: previewPlayer.playbackState === MediaPlayer.PlayingState ? "暂停" : "播放"
                                    Layout.preferredWidth: 90
                                    Layout.preferredHeight: 34
                                    background: Rectangle { color: parent.hovered ? "#0288D1" : "#039BE5"; radius: 4 }
                                    contentItem: Text { text: parent.text; color: "white"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                    onClicked: {
                                        if (previewPlayer.playbackState === MediaPlayer.PlayingState) previewPlayer.pause()
                                        else previewPlayer.play()
                                    }
                                }

                                Button {
                                    text: "停止"
                                    Layout.preferredWidth: 90
                                    Layout.preferredHeight: 34
                                    background: Rectangle { color: parent.hovered ? Theme.hover : Theme.control; radius: 4; border.color: Theme.border }
                                    contentItem: Text { text: parent.text; color: Theme.text; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                    onClicked: previewPlayer.stop()
                                }
                            }
                        }

                        Text {
                            anchors.centerIn: parent
                            width: parent.width - 40
                            visible: root.previewKind !== "image" && root.previewKind !== "text" && root.previewKind !== "audio"
                            text: root.previewText !== "" ? root.previewText : (root.previewSource !== "" ? root.previewSource : "暂无可预览内容")
                            color: Theme.muted
                            font.pixelSize: 14
                            wrapMode: Text.WordWrap
                            horizontalAlignment: Text.AlignHCenter
                        }
                    }
                }
            }
        }
    }

    Popup {
        id: toastMsg
        modal: false
        closePolicy: Popup.NoAutoClose
        z: 2147483647
        x: Math.round((root.width - width) / 2)
        y: 40
        height: 40
        leftPadding: 20
        rightPadding: 20
        opacity: 0
        background: Rectangle { color: Theme.control; radius: 6; border.color: Theme.border }
        contentItem: Text {
            id: toastText
            text: root.toastMessage
            color: Theme.text
            font.pixelSize: 13
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        SequentialAnimation {
            id: toastAnim
            NumberAnimation { target: toastMsg; property: "opacity"; to: 1.0; duration: 300 }
        }
    }

    Timer {
        id: toastCloseTimer
        interval: 2300
        onTriggered: {
            toastMsg.opacity = 0
            toastMsg.close()
        }
    }

    Component.onDestruction: {
        toastCloseTimer.stop()
        previewPlayer.stop()
    }

    MediaPlayer {
        id: previewPlayer
        audioOutput: previewAudio
    }

    AudioOutput {
        id: previewAudio
    }


    FileDialog {
        id: fileDialog
        title: "选择导入的文件"
        onAccepted: {
            selectedPathInput.text = root.localPathFromUrl(selectedFile)
        }
    }

    FolderDialog {
        id: folderDialog
        title: "选择导入的文件夹"
        onAccepted: {
            selectedPathInput.text = root.localPathFromUrl(selectedFolder)
        }
    }

    // 增：新增源数据集弹窗
    Dialog {
        id: createDialog
        title: "导入源数据集"
        width: 450
        modal: true
        standardButtons: Dialog.Ok | Dialog.Cancel
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        onOpened: {
            importModeCombo.currentIndex = 1
            inputType.currentIndex = 0
        }

        background: Rectangle {
            color: Theme.control
            border.color: Theme.border
            radius: 8
        }

        ColumnLayout {
            anchors.fill: parent
            spacing: 15

            TextField {
                id: inputName
                placeholderText: "输入源数据集名称"
                Layout.fillWidth: true
                color: Theme.text
                placeholderTextColor: Theme.muted
                background: Rectangle {
                    color: Theme.row
                    border.color: Theme.border
                    radius: 4
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                StableComboBox {
                    id: importModeCombo
                    model: ["导入文件", "导入文件夹"]
                    currentIndex: 1
                    Layout.preferredWidth: 100
                    background: Rectangle {
                        color: Theme.row
                        border.color: Theme.border
                        radius: 4
                    }
                    contentItem: Text {
                        text: importModeCombo.currentText
                        color: Theme.text
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 10
                    }
                    onCurrentIndexChanged: selectedPathInput.text = ""
                }

                TextField {
                    id: selectedPathInput
                    placeholderText: "未选择路径..."
                    readOnly: true
                    Layout.fillWidth: true
                    color: Theme.text
                    placeholderTextColor: Theme.muted
                    background: Rectangle {
                        color: Theme.row
                        border.color: Theme.border
                        radius: 4
                    }
                }

                Button {
                    text: "浏览"
                    Layout.preferredHeight: 35
                    background: Rectangle {
                        color: parent.hovered ? Theme.hover : Theme.control
                        radius: 4
                        border.color: Theme.border
                    }
                    contentItem: Text {
                        text: parent.text
                        color: Theme.text
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        if (importModeCombo.currentIndex === 0) fileDialog.open()
                        else folderDialog.open()
                    }
                }
            }

            StableComboBox {
                id: inputType
                model: ["图像", "文本", "音频"]
                currentIndex: 0
                Layout.fillWidth: true
                background: Rectangle {
                    color: Theme.row
                    border.color: Theme.border
                    radius: 4
                }
                contentItem: Text {
                    text: inputType.currentText
                    color: Theme.text
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 10
                }
            }

            Label {
                text: "注：默认存入 Source 根路径"
                color: Theme.muted
                font.pixelSize: 11
            }
        }
        onAccepted: {
            var path = selectedPathInput.text.trim()
            if (path === "") {
                root.showToast("请选择要导入的文件或文件夹")
                return
            }
            var finalName = inputName.text.trim()
            if (finalName === "") finalName = root.datasetNameFromPath(path)
            if (finalName === "") {
                root.showToast("请输入源数据集名称")
                return
            }
            root.importing = true
            root.pendingImportArgs = {
                finalName: finalName,
                typeText: inputType.currentText,
                path: path,
                isFile: importModeCombo.currentIndex === 0
            }
            inputName.text = ""
            selectedPathInput.text = ""
            importDeferTimer.start()
        }
    }

    // 改：修改弹窗
    Popup {
        id: editDialog
        property int datasetId: -1
        property string editName: ""
        property string editType: "图像"

        width: 420
        height: 240
        modal: true
        focus: true
        x: Math.round((parent.width - width) / 2)
        y: Math.round((parent.height - height) / 2)
        closePolicy: Popup.CloseOnEscape

        background: Rectangle {
            color: Theme.control
            border.color: Theme.border
            radius: 8
        }

        onOpened: {
            editNameInput.text = editName
            editTypeCombo.currentIndex = Math.max(0, editTypeCombo.find(editType))
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 16

            Text {
                text: "修改数据集信息"
                color: Theme.text
                font.pixelSize: 16
                font.bold: true
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 15
                Label {
                    text: "数据集名称:"
                    color: Theme.muted
                    font.pixelSize: 14
                    Layout.preferredWidth: 80
                    horizontalAlignment: Text.AlignRight
                }
                TextField {
                    id: editNameInput
                    Layout.fillWidth: true
                    Layout.preferredHeight: 36
                    color: Theme.text
                    font.pixelSize: 13
                    leftPadding: 10
                    verticalAlignment: TextInput.AlignVCenter
                    background: Rectangle {
                        color: Theme.row
                        border.color: Theme.border
                        radius: 4
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 15
                Label {
                    text: "数据类型:"
                    color: Theme.muted
                    font.pixelSize: 14
                    Layout.preferredWidth: 80
                    horizontalAlignment: Text.AlignRight
                }
                StableComboBox {
                    id: editTypeCombo
                    model: ["图像", "文本", "音频"]
                    Layout.fillWidth: true
                    Layout.preferredHeight: 36
                    background: Rectangle {
                        color: Theme.row
                        border.color: Theme.border
                        radius: 4
                    }
                    contentItem: Text {
                        text: editTypeCombo.currentText
                        color: Theme.text
                        font.pixelSize: 13
                        verticalAlignment: Text.AlignVCenter
                        padding: 10
                    }
                }
            }

            Item { Layout.fillHeight: true }

            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                Item { Layout.fillWidth: true }

                Rectangle {
                    width: 80; height: 36; color: primaryColor; radius: 4
                    Text { text: "确认"; color: "#FFFFFF"; anchors.centerIn: parent; font.pixelSize: 13; font.bold: true }
                    MouseArea {
                        anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            var result = backendService.updateDataset(editDialog.datasetId, editNameInput.text, editTypeCombo.currentText)
                            if (result && result.status === "success") {
                                showToast("数据集信息已更新")
                                loadData()
                            } else {
                                showToast((result && result.message) ? result.message : "更新失败")
                            }
                            editDialog.close()
                        }
                    }
                }
                Rectangle {
                    width: 80; height: 36; color: "transparent"
                    border.color: Theme.border; border.width: 1; radius: 4
                    Text { text: "取消"; color: Theme.text; anchors.centerIn: parent; font.pixelSize: 13 }
                    MouseArea {
                        anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                        onClicked: editDialog.close()
                    }
                }
            }
        }
    }
    // ================= 二次确认删除弹窗 =================
    Popup {
        id: deleteConfirmPopup
        width: 320
        height: 190
        modal: true
        focus: true
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: Theme.control; radius: 8; border.color: "#E11D48"; border.width: 1 }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 20
            spacing: 15

            RowLayout {
                spacing: 10
                Text { text: "⚠️"; font.pixelSize: 20 }
                Text { text: "确认删除此源数据集吗？"; color: Theme.text; font.pixelSize: 15; font.bold: true }
            }

            Text { text: "删除后将无法恢复，相关文件将从磁盘中永久移除。"; color: Theme.muted; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }

            Item { Layout.fillHeight: true }

            RowLayout {
                Layout.fillWidth: true
                spacing: 15
                Item { Layout.fillWidth: true }
                Button {
                    text: "取消"
                    Layout.preferredWidth: 80; Layout.preferredHeight: 30
                    background: Rectangle { color: "transparent"; border.color: Theme.border; border.width: 1; radius: 4 }
                    contentItem: Text { text: parent.text; color: Theme.muted; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: deleteConfirmPopup.close()
                }
                Button {
                    text: "确认删除"
                    Layout.preferredWidth: 80; Layout.preferredHeight: 30
                    background: Rectangle { color: "#E11D48"; radius: 4 }
                    contentItem: Text { text: parent.text; color: "white"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: {
                        if (root.pendingDeleteId !== -1) {
                            backendService.deleteDataset(root.pendingDeleteId)
                            root.loadData() // 刷新列表
                        }
                        deleteConfirmPopup.close()
                    }
                }
            }
        }
    }

    // ======== 导入加载遮罩 ========
    Timer {
        id: importDeferTimer
        interval: 50
        repeat: false
        onTriggered: {
            if (!root.pendingImportArgs) return
            var args = root.pendingImportArgs
            var res = backendService.createDataset(args.finalName, args.typeText, "")
            if (res && res.status === "success") {
                var newDatasetId = res.id
                var importResult = null
                if (args.isFile) importResult = backendService.uploadFile(newDatasetId, args.path)
                else importResult = backendService.importFolder(newDatasetId, args.path, true)
                if (!importResult || importResult.status !== "success") {
                    root.showToast(importResult && importResult.message ? importResult.message : "导入失败")
                }
            } else {
                root.showToast(res && res.message ? res.message : "创建数据集失败")
            }
            root.importing = false
            root.pendingImportArgs = null
            root.loadData()
        }
    }

    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.6)
        visible: root.importing
        z: 999

        MouseArea { anchors.fill: parent }

        Rectangle {
            width: 260
            height: 120
            radius: 12
            color: Theme.panel
            border.color: Theme.border
            anchors.centerIn: parent

            ColumnLayout {
                anchors.centerIn: parent
                spacing: 15
                BusyIndicator {
                    Layout.alignment: Qt.AlignHCenter
                    running: root.importing
                    implicitWidth: 40
                    implicitHeight: 40
                }
                Label {
                    text: "正在导入数据集..."
                    color: Theme.text
                    font.pixelSize: 14
                    font.bold: true
                    Layout.alignment: Qt.AlignHCenter
                }
                Label {
                    text: "大文件可能需要较长时间，请耐心等待"
                    color: Theme.muted
                    font.pixelSize: 11
                    Layout.alignment: Qt.AlignHCenter
                }
            }
        }
    }

}
