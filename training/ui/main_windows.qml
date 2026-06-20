import QtQuick 2.15
import QtQuick.Window 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."
import "views"

ApplicationWindow {
    id: root
    visible: true
    width: 1400
    height: 800
    title: qsTr("智能应用增量样本生成软件")

    Component.onCompleted: backendService.getSetting("ui.theme")

    Connections {
        target: backendService
        function onSettingValueLoaded(key, value) {
            if (key === "ui.theme" && value) Theme.setMode(String(value))
        }
    }

    // 全局主题配色属性
    property color bgDark: Theme.bg
    property color panelBg: Theme.panel
    property color primaryColor: Theme.primary
    property color secondaryColor: Theme.secondary
    property color textColor: Theme.text
    property color textMuted: Theme.muted
    property color borderColor: Theme.border

    // ================= 全局跨页面状态管理器 =================
    // 导航切换会销毁重建 Loader，通过这些属性保持评估/训练状态不丢失
    QtObject {
        id: appState

        // 评估历史 (序列化为 JSON 数组)
        property string evalHistoryJson: "[]"
        // 训练任务队列 (序列化为 JSON 数组)
        property string evalTaskQueueJson: "[]"
        // 评估结果 (序列化为 JSON 数组)
        property string evalResultJson: "[]"
        // 评估指标表头
        property string evalMetricHeadersJson: "[]"
        // 训练中标记
        property bool evalIsTraining: false
        // 任务计数器
        property int evalTaskCounter: 1
    }

    color: bgDark

    // ================= 顶部导航栏 =================
    Rectangle {
        id: header
        height: 64
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        color: Theme.header
        border.color: root.borderColor
        border.width: 1

        RowLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 20

            // Logo
            Rectangle {
                width: 32; height: 32
                radius: 8
                gradient: Gradient {
                    GradientStop { position: 0.0; color: root.primaryColor }
                    GradientStop { position: 1.0; color: root.secondaryColor }
                }
            }

            Text {
                text: "智能应用增量样本生成软件"
                font.pixelSize: 18
                font.bold: true
                color: root.textColor
                Layout.fillWidth: true
            }
        }
    }

    // ================= 侧边导航栏 =================
    Rectangle {
        id: sidebar
        width: 250
        anchors.top: header.bottom
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        color: Theme.sidebar
        border.color: root.borderColor
        border.width: 1

        // 搜索框区域已删除

        // 导航菜单数据模型
        ListModel {
                id: navModel
                // 核心功能
                ListElement { isHeader: false; name: "数据管理"; source: "views/DataManageView.qml"; icon: "🗄️" }
                ListElement { isHeader: false; name: "数据生成"; source: "views/SampleGenView.qml"; icon: "⚡" }
                ListElement { isHeader: false; name: "数据清洗"; source: "views/DataCleanView.qml"; icon: "🧹" }
                ListElement { isHeader: false; name: "多专业智能应用仿真模型"; source: "views/EvaluateView.qml"; icon: "📈" }
                // 边缘设备管理
                ListElement { isHeader: false; name: "边缘设备管理"; source: "views/EdgeDeviceView.qml"; icon: "📡" }
                // 算法与参数配置
                ListElement { isHeader: false; name: "算法与参数配置"; source: "views/AlgoConfigView.qml"; icon: "🧩" }
                // 系统
                ListElement { isHeader: false; name: "系统设置"; source: "views/SystemSettingsView.qml"; icon: "⚙" }
            }

        // 导航菜单列表
        ListView {
            id: navList
            anchors.top: parent.top // 改为直接锚定到父级顶部
            anchors.topMargin: 20
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            model: navModel
            currentIndex: 0 // 默认选中"数据管理"
            clip: true

            delegate: Loader {
                width: navList.width
                height: model.isHeader ? 40 : 50
                sourceComponent: model.isHeader ? headerDelegate : itemDelegate

                // 分组标题组件
                Component {
                    id: headerDelegate
                    Item {
                        Text {
                            text: model.name
                            color: root.textMuted
                            font.pixelSize: 13
                            font.bold: true
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 8
                            anchors.left: parent.left
                            anchors.leftMargin: 25
                        }
                    }
                }

                // 可点击的菜单项组件
                // 可点击的菜单项组件
Component {
    id: itemDelegate
    Rectangle {
        id: itemBg
        anchors.fill: parent
        anchors.leftMargin: 15
        anchors.rightMargin: 15
        anchors.topMargin: 2
        anchors.bottomMargin: 2
        radius: 6
        // 选中时的背景色保持原来的半透明蓝
        color: navList.currentIndex === index ? Qt.rgba(22/255, 93/255, 255/255, 0.2) : "transparent"

        // 选中时的左侧高亮蓝条
        Rectangle {
            width: 3
            height: parent.height - 12
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            radius: 1.5
            color: root.primaryColor
            visible: navList.currentIndex === index
        }

        // 图标与文字布局
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 18
            spacing: 12

            Text {
                text: model.icon
                font.pixelSize: 18
                // --- 核心修改：统一设置为蓝色 ---
                color: root.primaryColor
                // 未选中时稍微降低透明度，选中时全亮
                opacity: navList.currentIndex === index ? 1.0 : 0.6
                verticalAlignment: Text.AlignVCenter
            }

            Text {
                text: model.name
                font.pixelSize: 14
                color: root.textColor
                font.bold: navList.currentIndex === index
                Layout.fillWidth: true
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
        }

        // 交互逻辑保持不变
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            onClicked: {
                navList.currentIndex = index
                viewStack.currentIndex = index
            }
            onEntered: if(navList.currentIndex !== index) itemBg.color = Qt.rgba(255/255, 255/255, 255/255, 0.05)
            onExited: if(navList.currentIndex !== index) itemBg.color = "transparent"
        }
    }
}
            }
        }
    }

    // ================= 右侧主工作区 (StackLayout: 所有页面常驻不销毁) =================
    Item {
        id: mainContentArea
        anchors.top: header.bottom
        anchors.bottom: parent.bottom
        anchors.left: sidebar.right
        anchors.right: parent.right

        property bool page0Loaded: true
        property bool page1Loaded: false; property bool page2Loaded: false
        property bool page3Loaded: false; property bool page4Loaded: false
        property bool page5Loaded: false; property bool page6Loaded: false
        function markLoaded(idx) {
            if (idx===1) page1Loaded=true; else if (idx===2) page2Loaded=true
            else if (idx===3) page3Loaded=true; else if (idx===4) page4Loaded=true
            else if (idx===5) page5Loaded=true; else if (idx===6) page6Loaded=true
        }

        StackLayout {
            id: viewStack
            anchors.fill: parent
            anchors.margins: 20
            currentIndex: 0
            onCurrentIndexChanged: mainContentArea.markLoaded(currentIndex)

            Loader { source: "views/DataManageView.qml";  active: true;                 asynchronous: true }
            Loader { source: "views/SampleGenView.qml";    active: mainContentArea.page1Loaded;          asynchronous: true }
            Loader { source: "views/DataCleanView.qml";    active: mainContentArea.page2Loaded;          asynchronous: true }
            Loader { source: "views/EvaluateView.qml";     active: true;          asynchronous: true }
            Loader { source: "views/EdgeDeviceView.qml";   active: mainContentArea.page4Loaded;          asynchronous: true }
            Loader { source: "views/AlgoConfigView.qml";   active: mainContentArea.page5Loaded;          asynchronous: true }
            Loader { source: "views/SystemSettingsView.qml"; active: mainContentArea.page6Loaded;        asynchronous: true }
        }
    }
}
