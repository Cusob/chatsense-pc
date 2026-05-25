"""Eight-bar gauge chart for dimension scores.

Each bar spans 0-100 with three colored zones:
  - 0-50:  red (unhealthy low)
  - 50-75: green (healthy)
  - 75-100: red (unhealthy high)

A pointer line marks the current score position on each bar.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt, QRect, QPointF
from PyQt6.QtGui import (
    QPainter, QColor, QFont, QPolygonF,
)

from models.analysis_result import DimensionScores
from ui.widgets.colors import score_color


class BarGauge(QWidget):
    """Horizontal bar gauge chart showing 8 dimension scores."""

    BAR_HEIGHT = 22
    GAP = 8
    LABEL_WIDTH = 105
    SCORE_WIDTH = 30
    PADDING = 6
    HEALTH_LOW = 50
    HEALTH_HIGH = 75

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scores: DimensionScores | None = None
        self._dim_names: list[tuple[str, str]] = []
        self.setMinimumHeight(300)

    def render(self, scores: DimensionScores):
        self._scores = scores
        if not self._dim_names:
            self._dim_names = scores.dimension_names()
        self.update()

    def clear(self):
        self._scores = None
        self.update()

    def paintEvent(self, event):
        if not self._scores:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = self.width() - 2 * self.PADDING
        bar_left = self.PADDING + self.LABEL_WIDTH
        bar_width = w - self.LABEL_WIDTH - self.SCORE_WIDTH
        if bar_width <= 0:
            return

        health_start = int(bar_left + bar_width * self.HEALTH_LOW / 100)
        health_end = int(bar_left + bar_width * self.HEALTH_HIGH / 100)

        for i, (key, name) in enumerate(self._dim_names):
            y = self.PADDING + i * (self.BAR_HEIGHT + self.GAP)
            score = getattr(self._scores, key, 50)

            # Label
            label_font = QFont("Microsoft YaHei", 9)
            painter.setFont(label_font)
            painter.setPen(QColor("#333"))
            painter.drawText(
                QRect(self.PADDING, y, self.LABEL_WIDTH, self.BAR_HEIGHT),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                name,
            )

            # Bar background with color zones
            bar_rect = QRect(bar_left, y, bar_width, self.BAR_HEIGHT)

            # Draw health zone (green)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#81C784"))  # softer green
            health_rect = QRect(health_start, y, health_end - health_start, self.BAR_HEIGHT)
            painter.drawRoundedRect(health_rect, 2, 2)

            # Draw unhealthy zones (red)
            low_rect = QRect(bar_left, y, health_start - bar_left, self.BAR_HEIGHT)
            painter.setBrush(QColor("#E57373"))  # softer red
            painter.drawRoundedRect(low_rect, 2, 2)

            high_rect = QRect(health_end, y, bar_left + bar_width - health_end, self.BAR_HEIGHT)
            painter.drawRoundedRect(high_rect, 2, 2)

            # Draw fill bar with lighter version of score color
            sc = score_color(score)
            pointer_x = int(bar_left + bar_width * score / 100)
            fill_rect = QRect(bar_left, y + 7, pointer_x - bar_left, self.BAR_HEIGHT - 14)
            fill_c = QColor(sc)
            fill_c.setAlpha(120)  # translucent
            painter.setBrush(fill_c)
            painter.drawRoundedRect(fill_rect, 2, 2)

            # Draw pointer triangle in blue
            painter.setBrush(QColor("#2196F3"))
            tri_size = 8
            tri_y = y + self.BAR_HEIGHT // 2
            polygon = QPolygonF()
            polygon.append(QPointF(pointer_x, tri_y - tri_size))
            polygon.append(QPointF(pointer_x + tri_size, tri_y))
            polygon.append(QPointF(pointer_x, tri_y + tri_size))
            painter.drawPolygon(polygon)

            # Score number
            painter.setPen(QColor(sc))
            score_font = QFont("Consolas", 11)
            score_font.setBold(True)
            painter.setFont(score_font)
            painter.drawText(
                QRect(bar_left + bar_width + 4, y, self.SCORE_WIDTH, self.BAR_HEIGHT),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                str(score),
            )

        painter.end()
