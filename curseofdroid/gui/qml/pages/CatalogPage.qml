import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

ColumnLayout {
    id: page
    required property var catalog
    property bool recovery: false
    spacing: 16
    function applyFilters() {
        catalog.setFilters(filter.text, project.currentIndex > 0 ? project.currentText : "",
            android.currentIndex > 0 ? android.currentText : "", ["", "recent", "old", "unknown", "future"][age.currentIndex],
            ["newest", "oldest", "project"][sort.currentIndex])
    }
    PageHeader {
        Layout.fillWidth: true
        title: page.recovery ? qsTr("Recovery, with the right context.") : qsTr("Find your next Android.")
        subtitle: page.recovery ? qsTr("TWRP, OrangeFox and explicitly published LineageOS recovery images. Methods must be checked per device.") : qsTr("Explore the existing ROM provider catalog. A codename match starts the research; it does not certify compatibility.")
    }
    InfoCard {
        Layout.fillWidth: true
        padding: 16
        contentItem: ColumnLayout {
            spacing: 10
            RowLayout {
                Layout.fillWidth: true
                SearchField {
                    id: codename
                    objectName: page.recovery ? "recoveryCodename" : "romCodename"
                    Layout.fillWidth: true
                    placeholderText: qsTr("Device codename, e.g. lavender")
                    maximumLength: 64
                    enabled: !page.catalog.busy
                    onAccepted: page.catalog.search(text)
                }
                AppButton { text: qsTr("Search"); kind: "primary"; enabled: !page.catalog.busy; onClicked: page.catalog.search(codename.text) }
                AppButton { text: qsTr("Use selected device"); enabled: !page.catalog.busy && Object.keys(backend.device).length > 0; onClicked: page.catalog.searchSelected() }
            }
            RowLayout {
                visible: page.catalog.busy
                Layout.fillWidth: true
                UiText { text: qsTr("Providers completed: ") + page.catalog.completedProviders + " / " + page.catalog.providerCount; secondary: true; Layout.fillWidth: true }
                AppButton { text: qsTr("Cancel"); enabled: page.catalog.state !== "cancelling"; onClicked: page.catalog.cancel() }
            }
            AppProgressBar { visible: page.catalog.busy; Layout.fillWidth: true; from: 0; to: page.catalog.providerCount; value: page.catalog.completedProviders; Accessible.name: qsTr("Catalog providers completed") }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        SearchField { id: filter; objectName: "catalogFilter"; Layout.fillWidth: true; placeholderText: qsTr("Filter results…"); onTextChanged: page.applyFilters() }
        AppButton { id: filterOptions; visible: page.width < 850; text: checked ? qsTr("Hide filters") : qsTr("Filters"); checkable: true; kind: checked ? "primary" : "secondary" }
    }
    GridLayout {
        visible: page.width >= 850 || filterOptions.checked
        Layout.fillWidth: true
        columns: page.width < 850 ? 2 : 4
        rowSpacing: 10
        columnSpacing: 10
        AppComboBox { id: project; Layout.fillWidth: true; model: [qsTr("All projects")].concat(page.catalog.projects); onActivated: page.applyFilters(); Accessible.name: qsTr("Project filter") }
        AppComboBox { id: android; enabled: !page.catalog.busy; Layout.fillWidth: true; model: [qsTr("All Android")].concat(page.catalog.androidVersions); onActivated: page.applyFilters(); Accessible.name: qsTr("Android filter") }
        AppComboBox { id: age; Layout.fillWidth: true; model: [qsTr("All dates"), qsTr("Within 183 days"), qsTr("Older than 183 days"), qsTr("Unknown date"), qsTr("Future date")]; onActivated: page.applyFilters(); Accessible.name: qsTr("Release age filter") }
        AppComboBox { id: sort; Layout.fillWidth: true; model: [qsTr("Newest first"), qsTr("Oldest first"), qsTr("Project A–Z")]; onActivated: page.applyFilters(); Accessible.name: qsTr("Sort results") }
    }
    RowLayout {
        Layout.fillWidth: true
        UiText { text: page.catalog.rows.length + " / " + page.catalog.totalCount + qsTr(" results") + (page.catalog.query ? "  ·  " + page.catalog.query : ""); secondary: true; font.pixelSize: 12 * theme.scale; Layout.fillWidth: true }
        StatusBadge { text: page.catalog.state; tone: page.catalog.state === "error" ? "warning" : "neutral" }
    }
    UiText { visible: page.catalog.state === "cancelled" || page.catalog.state === "cancelling"; text: qsTr("Cancellation waits for the current network request; completed results are partial."); color: theme.colors.warning; font.pixelSize: 12 * theme.scale; Layout.fillWidth: true }
    UiText { visible: page.catalog.state === "invalidated"; text: qsTr("Device selection changed. These results were cleared; search the selected device again."); color: theme.colors.warning; Layout.fillWidth: true }
    Disclosure { objectName: page.recovery ? "recoveryErrors" : "romErrors"; visible: page.catalog.errors.length > 0; Layout.fillWidth: true; messages: page.catalog.errors }
    ListView {
        id: results
        objectName: page.recovery ? "recoveryResults" : "romResults"
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        spacing: 12
        model: page.catalog.rows
        reuseItems: true
        delegate: CatalogCard {
            required property var modelData
            width: results.width
            build: modelData
            onInspectRequested: function(identifier) { page.catalog.select(identifier); details.open() }
        }
        ScrollBar.vertical: ScrollBar {}
        ColumnLayout {
            anchors.centerIn: parent
            width: Math.max(200, parent.width - 48)
            visible: page.catalog.rows.length === 0
            spacing: 12
            UiText { text: page.catalog.state === "idle" ? qsTr("Start with a device codename.") : (page.catalog.busy ? qsTr("Asking the publishers…") : (page.catalog.state === "error" ? qsTr("The sources could not be reached.") : qsTr("No matching results."))); font.pixelSize: 21 * theme.scale; font.weight: Font.DemiBold; Layout.fillWidth: true }
            UiText { text: page.catalog.state === "idle" ? qsTr("Search manually or use the selected device. Results arrive as each provider finishes.") : qsTr("Check the codename, filters and provider errors. An unavailable source does not prove that no build exists."); secondary: true; Layout.fillWidth: true }
        }
    }
    UiText { text: qsTr("Open build details to queue a download. Release age and checksum availability do not certify installation compatibility."); secondary: true; font.pixelSize: 11 * theme.scale; Layout.fillWidth: true }
    CatalogDetails { id: details; parent: Overlay.overlay; anchors.centerIn: parent; catalog: page.catalog }
    Connections {
        target: page.catalog
        function onChanged() {
            if (page.catalog.state === "searching" && page.catalog.completedProviders === 0) {
                codename.text = page.catalog.query.split(", ")[0]
                filter.text = ""; project.currentIndex = 0; android.currentIndex = 0; age.currentIndex = 0
            }
        }
    }
}
