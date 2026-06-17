import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import ".."

Item {
    id: root
    anchors.fill: parent

    // ================= 全局颜色变量 =================
    property color bgDark: Theme.bg
    property color panelBg: Theme.panel
    property color primaryColor: Theme.primary
    property color secondaryColor: "#36CFC9"
    property color successColor: "#52C41A"
    property color warningColor: Theme.warning
    property color dangerColor: "#FF4D4F"
    property color textColor: Theme.text
    property color textMuted: Theme.muted
    property color borderColor: Theme.border
    
    // ================= 数据模型 =================
    ListModel {
        id: statsModel
        ListElement { title: "总数据集"; val: "0"; sub: "↑ 0% vs 上月"; subC: "#52C41A"; prog: 0; progC: Theme.primary }
        ListElement { title: "总样本数"; val: "0"; sub: "↑ 0% vs 上月"; subC: "#52C41A"; prog: 0; progC: "#36CFC9" }
        ListElement { title: "已处理样本"; val: "0"; sub: "↓ 0% vs 上月"; subC: "#FF4D4F"; prog: 0; progC: Theme.warning }
        ListElement { title: "存储空间"; val: "0 GB"; sub: "0% 已使用"; subC: Theme.muted; prog: 0; progC: "#52C41A" }
    }
    
    ListModel {
        id: activityModel
    }
    
    ListModel {
        id: datasetModel
    }
    
    // ================= 初始化 =================
    Component.onCompleted: {
        // 获取系统统计数据
        backendService.getSystemStats();
        // 获取最近活动
        backendService.getRecentActivities(5);
        // 获取数据集列表
        backendService.getDatasets(1, 10, "");
        // 获取样本增长趋势
        backendService.getSampleGrowthTrend("week");
        // 获取数据类型分布
        backendService.getDataTypeDistribution();
    }
    
    // ================= 信号连接 =================
    Connections {
        target: backendService
        function onSystemStatsUpdated(stats) {
            // 更新数据指标卡片
            statsModel.set(0, { val: stats.total_datasets, sub: "↑ 12% vs 上月", subC: "#52C41A", prog: stats.total_datasets / 60 });
            statsModel.set(1, { val: stats.total_samples, sub: "↑ 23% vs 上月", subC: "#52C41A", prog: stats.total_samples / 25000 });
            statsModel.set(2, { val: stats.processed_samples, sub: "↓ 4% vs 上月", subC: "#FF4D4F", prog: stats.processed_samples / 20000 });
            statsModel.set(3, { val: stats.total_storage, sub: stats.storage_usage + "% 已使用", subC: Theme.muted, prog: stats.storage_usage / 100 });
        }
        
        function onRecentActivitiesUpdated(activities) {
            // 更新最近活动列表
            activityModel.clear();
            
            // 判空保护
            if (!activities) {
                console.log("提示：获取到的 activities 为空");
                return;
            }
            
            for (var i = 0; i < activities.length; i++) {
                activityModel.append(activities[i]);
            }
        }
        
        function onDatasetsUpdated(datasets) {
            // 更新数据集列表
            datasetModel.clear();
            
            // 判空保护
            if (!datasets || !datasets.items) {
                console.log("提示：获取到的 datasets 为空或格式不正确");
                return;
            }
            
            for (var i = 0; i < datasets.items.length; i++) {
                var dataset = datasets.items[i];
                var statusColor = "#52C41A"; // 已处理
                if (dataset.status === "created") {
                    statusColor = Theme.warning; // 处理中
                } else if (dataset.status === "error") {
                    statusColor = "#FF4D4F"; // 错误
                }
                
                datasetModel.append({
                    id: dataset.id,
                    name: dataset.name,
                    type: dataset.type,
                    count: dataset.total_samples,
                    size: (dataset.size / (1024 * 1024 * 1024)).toFixed(1) + " GB",
                    status: dataset.status === "processed" ? "已处理" : (dataset.status === "created" ? "处理中" : "错误"),
                    tagColor: statusColor
                });
            }
        }
    }

    // ================= 主看板滚动视图 =================
    ScrollView {
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth

        ColumnLayout {
            width: parent.width
            spacing: 20

            // --- 顶部：标题与按钮 ---
            RowLayout {
                Layout.fillWidth: true
                Layout.bottomMargin: 10
                ColumnLayout {
                    spacing: 4
                    Text { text: "数据管理"; color: textColor; font.pixelSize: 22; font.bold: true }
                    Text { text: "查看和管理系统中的所有数据资源"; color: textMuted; font.pixelSize: 13 }
                }
                Item { Layout.fillWidth: true }

                Rectangle {
                    width: 100; height: 36; radius: 4; color: primaryColor
                    Text { text: "导入数据"; color: "#FFFFFF"; anchors.centerIn: parent; font.pixelSize: 13; font.bold: true }
                    MouseArea {
                        anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onEntered: parent.opacity = 0.8; onExited: parent.opacity = 1.0
                        onClicked: importDataPopup.open()
                    }
                }
            }

            // --- 第一排：数据指标卡片 ---
            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 110
                spacing: 20

                Repeater {
                    model: statsModel

                    Rectangle {
                        Layout.fillWidth: true; Layout.fillHeight: true; color: panelBg; radius: 8; border.color: borderColor; border.width: 1
                        ColumnLayout {
                            anchors.fill: parent; anchors.margins: 15; spacing: 5
                            Text { text: model.title; color: textMuted; font.pixelSize: 13 }
                            Text { text: model.val; color: textColor; font.pixelSize: 24; font.bold: true; Layout.topMargin: 5 }
                            Text { text: model.sub; color: model.subC; font.pixelSize: 12 }
                            Item { Layout.fillHeight: true }
                            Rectangle {
                                Layout.fillWidth: true; height: 4; radius: 2; color: bgDark
                                Rectangle { width: parent.width * model.prog; height: parent.height; radius: 2; color: model.progC }
                            }
                        }
                    }
                }
            }
        }
    }

    // ================= 弹窗 1：数据导入弹窗 =================
    Popup {
        id: importDataPopup
        width: 800
        height: 660
        x: Math.round((parent.width - width) / 2)
        y: Math.round((parent.height - height) / 2)
        modal: true
        focus: true
        closePolicy: Popup.NoAutoClose

        Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.6) }
        background: Rectangle { color: panelBg; radius: 12; border.color: borderColor; border.width: 1 }

        // 记录当前选择的数据类型 (0: 图像, 1: 音频, 2: 文本)
        property int selectedDataType: 0

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 20

            // --- 1. 弹窗头部 ---
            RowLayout {
                Layout.fillWidth: true
                Layout.maximumHeight: 30
                Rectangle { width: 24; height: 24; color: "transparent"
                    Text { text: "📥"; font.pixelSize: 20; anchors.centerIn: parent }
                }
                Text { text: "数据导入"; color: textColor; font.pixelSize: 18; font.bold: true }

                Item { Layout.fillWidth: true } // 弹簧

                Rectangle {
                    width: 28; height: 28; radius: 14; color: bgDark; border.color: borderColor; border.width: 1
                    Text { text: "×"; color: textColor; anchors.centerIn: parent; font.pixelSize: 18; anchors.verticalCenterOffset: -2 }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: importDataPopup.close() }
                }
            }

            // --- 4. 底部操作栏 ---
            RowLayout {
                Layout.fillWidth: true
                Layout.maximumHeight: 40
                Item { Layout.fillWidth: true }

                Rectangle {
                    width: 80; height: 36; color: "transparent"; border.color: borderColor; border.width: 1; radius: 4
                    Text { text: "取消"; color: textColor; anchors.centerIn: parent; font.pixelSize: 13 }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: importDataPopup.close() }
                }
                Rectangle {
                    width: 100; height: 36; color: primaryColor; radius: 4
                    RowLayout {
                        anchors.centerIn: parent; spacing: 5
                        Text { text: "▶"; color: "black"; font.pixelSize: 10 }
                        Text { text: "开始导入"; color: "black"; font.pixelSize: 13; font.bold: true }
                    }
                    MouseArea { 
                        anchors.fill: parent; 
                        cursorShape: Qt.PointingHandCursor; 
                        onEntered: parent.opacity=0.8; 
                        onExited: parent.opacity=1.0;
                        onClicked: {
                            // 创建数据集
                            var datasetType = importDataPopup.selectedDataType === 0 ? "image" : (importDataPopup.selectedDataType === 1 ? "audio" : "text");
                            var datasetName = "新数据集_" + new Date().getTime();
                            var result = backendService.createDataset(datasetName, datasetType, "");
                            
                            if (result && result.status === "success") {
                                // 模拟导入操作
                                console.log("数据集创建成功，ID: " + result.id);
                                importDataPopup.close();
                                // 重新获取数据集列表
                                backendService.getDatasets(1, 10, "");
                            } else {
                                console.log("数据集创建失败: " + (result && result.message ? result.message : "未知错误"));
                            }
                        }
                    }
                }
            }
        }
    }
}



