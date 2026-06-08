import AppKit
import SwiftUI

struct FileListView: View {
    let files: [PanFile]
    @Binding var selection: Set<PanFile.ID>
    let open: (PanFile) -> Void
    @State private var isDraggingSelection = false
    @State private var dragShouldSelect = true

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Button {
                    toggleAll()
                } label: {
                    Image(systemName: allVisibleSelected ? "checkmark.square.fill" : "square")
                        .frame(width: 22)
                }
                .buttonStyle(.plain)
                .help(allVisibleSelected ? "取消全选" : "全选")

                Text("名称").frame(maxWidth: .infinity, alignment: .leading)
                Text("大小").frame(width: 96, alignment: .trailing)
                Text("修改时间").frame(width: 132, alignment: .leading)
                Text("类型").frame(width: 72, alignment: .leading)
            }
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 24)
            .padding(.vertical, 8)
            .background(.bar)

            ScrollView {
                LazyVStack(spacing: 0) {
                    ForEach(files) { file in
                        FileRowView(
                            file: file,
                            isSelected: selection.contains(file.id),
                            toggle: { toggle(file) },
                            selectSingle: { selectSingle(file) },
                            beginDragSelection: { beginDragSelection(file) },
                            applyDragSelection: { applyDragSelection(file) },
                            endDragSelection: { isDraggingSelection = false },
                            isDraggingSelection: isDraggingSelection,
                            open: {
                                selectSingle(file)
                                open(file)
                            }
                        )
                        .contextMenu {
                            if file.isDirectory {
                                Button("打开") {
                                    open(file)
                                }
                            }
                            Button(selection.contains(file.id) ? "取消选择" : "选择") {
                                toggle(file)
                            }
                        }
                    }
                }
                .padding(.vertical, 4)
            }
            .background(Color(nsColor: .textBackgroundColor))
        }
    }

    private var allVisibleSelected: Bool {
        !files.isEmpty && files.allSatisfy { selection.contains($0.id) }
    }

    private func toggleAll() {
        if allVisibleSelected {
            selection.subtract(files.map(\.id))
        } else {
            selection.formUnion(files.map(\.id))
        }
    }

    private func toggle(_ file: PanFile) {
        if selection.contains(file.id) {
            selection.remove(file.id)
        } else {
            selection.insert(file.id)
        }
    }

    private func selectSingle(_ file: PanFile) {
        if NSEvent.modifierFlags.contains(.command) {
            if selection.contains(file.id) {
                selection.remove(file.id)
            } else {
                selection.insert(file.id)
            }
        } else {
            selection = [file.id]
        }
    }

    private func beginDragSelection(_ file: PanFile) {
        isDraggingSelection = true
        dragShouldSelect = !selection.contains(file.id)
        applyDragSelection(file)
    }

    private func applyDragSelection(_ file: PanFile) {
        if dragShouldSelect {
            selection.insert(file.id)
        } else {
            selection.remove(file.id)
        }
    }
}

private struct FileRowView: View {
    let file: PanFile
    let isSelected: Bool
    let toggle: () -> Void
    let selectSingle: () -> Void
    let beginDragSelection: () -> Void
    let applyDragSelection: () -> Void
    let endDragSelection: () -> Void
    let isDraggingSelection: Bool
    let open: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Button {
                toggle()
            } label: {
                Image(systemName: isSelected ? "checkmark.square.fill" : "square")
                    .foregroundStyle(isSelected ? Color.white : Color.secondary)
                    .frame(width: 22, height: 22)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .simultaneousGesture(
                DragGesture(minimumDistance: 3)
                    .onChanged { _ in
                        if !isDraggingSelection {
                            beginDragSelection()
                        }
                    }
                    .onEnded { _ in
                        endDragSelection()
                    }
            )

            Image(systemName: file.isDirectory ? "folder" : "doc")
                .foregroundStyle(file.isDirectory ? .blue : .secondary)
                .frame(width: 22)
            Text(file.serverFilename)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
            Text(file.isDirectory ? "" : DisplayFormat.size(file.size))
                .font(.callout.monospacedDigit())
                .foregroundStyle(isSelected ? .white.opacity(0.86) : .secondary)
                .frame(width: 96, alignment: .trailing)
            Text(DisplayFormat.date(file.serverMTime))
                .foregroundStyle(isSelected ? .white.opacity(0.86) : .secondary)
                .frame(width: 132, alignment: .leading)
            Text(file.isDirectory ? "文件夹" : "文件")
                .foregroundStyle(isSelected ? .white.opacity(0.86) : .secondary)
                .frame(width: 72, alignment: .leading)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 7)
        .foregroundStyle(isSelected ? .white : .primary)
        .background {
            RoundedRectangle(cornerRadius: 7)
                .fill(isSelected ? Color.accentColor : Color.clear)
                .padding(.horizontal, 8)
                .padding(.vertical, 1)
        }
        .contentShape(Rectangle())
        .onTapGesture(count: 1) {
            selectSingle()
        }
        .onTapGesture(count: 2) {
            if file.isDirectory {
                open()
            } else {
                selectSingle()
            }
        }
        .onHover { hovering in
            if hovering && isDraggingSelection {
                applyDragSelection()
            }
        }
    }
}
