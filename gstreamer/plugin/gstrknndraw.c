/* SPDX-License-Identifier: LGPL-2.1+ */
/*
 * GStreamer RKNN Draw Plugin for RK3399Pro
 *
 * 元素名称: rknndraw
 * 类型:     GstVideoFilter (transform_frame_ip)
 * 功能:     在视频帧上绘制检测框和标签,
 *           检测结果从上游 rknninference 元素的 GstMeta (RknnDetectionMeta) 读取。
 *
 * Pipeline 示例:
 *   gst-launch-1.0 v4l2src ! videoconvert ! rknninference ! rknndraw ! autovideosink
 *
 * 属性:
 *   line-width:  边框线宽 (默认 2)
 *   font-scale:  字体大小 (默认 0.5)
 *   show-label:  是否显示标签 (默认 true)
 *   show-conf:   是否显示置信度 (默认 true)
 *
 * 依赖:
 *   - rknninference 元素 (提供 RknnDetectionMeta)
 *
 * 参考:
 *   - GStreamer Plugin Writer's Guide
 *   - gst-plugins-good/gst/videofilter/
 */

#include <gst/gst.h>
#include <gst/video/video.h>
#include <gst/video/gstvideofilter.h>
#include <string.h>
#include <stdio.h>

GST_DEBUG_CATEGORY_STATIC(rknn_draw_debug);
#define GST_CAT_DEFAULT rknn_draw_debug

/*
 * ── RknnDetectionMeta 类型引用 ────────────────────────────
 *
 * 此类型由 gstrknninference.c 注册。
 * 这里通过 GType API 动态查找 (运行时解析)。
 * 两个插件都加载时, GType 系统保证类型可用。
 */

/* GstMeta API type 查找函数 */
static GType _rknn_meta_api_type = 0;

static GType get_rknn_detection_meta_api_type(void)
{
    if (_rknn_meta_api_type == 0) {
        /* 运行时查找已注册的 GstMeta API type */
        _rknn_meta_api_type = gst_meta_api_type_register(
            "RknnDetectionMetaAPI", NULL);
    }
    return _rknn_meta_api_type;
}

/*
 * RknnDetectionMeta 内存布局 (与 gstrknninference.c 保持一致):
 *
 *   typedef struct {
 *       GstMeta parent;
 *       gint    num_detections;
 *       gfloat *boxes;        // [num * 6]: x1,y1,x2,y2,conf,class_id
 *       gchar **class_names;  // [num]
 *   } RknnDetectionMeta;
 *
 * 由于 C 语言没有反射, 我们通过 GstStructure 或直接偏移访问 meta 数据。
 * 更稳健的方式是共享一个头文件, 这里出于自包含目的使用运行时查找。
 */

/* ── 元素结构体 ────────────────────────────────────────── */
typedef struct _GstRknnDraw
{
    GstVideoFilter parent;

    /* 属性 */
    gint line_width;
    gdouble font_scale;
    gboolean show_label;
    gboolean show_conf;

    /* 颜色表 (10种预定义颜色, BGR) */
    struct {
        gint r, g, b;
    } colors[10];
} GstRknnDraw;

typedef struct _GstRknnDrawClass
{
    GstVideoFilterClass parent_class;
} GstRknnDrawClass;

/* ── GStreamer 类型注册 ────────────────────────────────── */
#define GST_TYPE_RKNN_DRAW (gst_rknn_draw_get_type())
G_DECLARE_FINAL_TYPE(GstRknnDraw, gst_rknn_draw,
                     GST, RKNN_DRAW, GstVideoFilter)

G_DEFINE_TYPE(GstRknnDraw, gst_rknn_draw, GST_TYPE_VIDEO_FILTER);

/* ── 属性定义 ──────────────────────────────────────────── */
enum
{
    PROP_0,
    PROP_LINE_WIDTH,
    PROP_FONT_SCALE,
    PROP_SHOW_LABEL,
    PROP_SHOW_CONF,
};

/* ── 绘制函数 ──────────────────────────────────────────── */
/*
 * draw_detection_box — 在帧上绘制单个检测框
 *
 * 直接在 GStreamer buffer 的内存上绘制 (零拷贝)。
 */
static void draw_detection_box(GstRknnDraw *self,
                               GstVideoFrame *frame,
                               gfloat x1, gfloat y1,
                               gfloat x2, gfloat y2,
                               gfloat confidence,
                               const gchar *class_name)
{
    GstVideoInfo *info = &frame->info;
    gint width = GST_VIDEO_INFO_WIDTH(info);
    gint height = GST_VIDEO_INFO_HEIGHT(info);
    gint stride = GST_VIDEO_INFO_PLANE_STRIDE(info, 0);
    guchar *data = (guchar *)GST_VIDEO_FRAME_PLANE_DATA(frame, 0);
    gint channels = 3;  /* BGR */

    /* 选择颜色 (基于 class_name hash) */
    gint color_idx = 0;
    if (class_name) {
        guint hash = 5381;
        for (const gchar *s = class_name; *s; s++)
            hash = ((hash << 5) + hash) + (guint)(*s);
        color_idx = hash % 10;
    }
    guchar r = self->colors[color_idx].r;
    guchar g = self->colors[color_idx].g;
    guchar b = self->colors[color_idx].b;

    /* 裁剪到帧边界 */
    gint ix1 = CLAMP((gint)x1, 0, width - 1);
    gint iy1 = CLAMP((gint)y1, 0, height - 1);
    gint ix2 = CLAMP((gint)x2, 0, width - 1);
    gint iy2 = CLAMP((gint)y2, 0, height - 1);

    gint lw = self->line_width;

    /* 绘制顶部和底部边框线 */
    for (gint dy = 0; dy < lw; dy++) {
        gint y_top = CLAMP(iy1 + dy, 0, height - 1);
        gint y_bot = CLAMP(iy2 - dy, 0, height - 1);

        for (gint x = ix1; x <= ix2; x++) {
            gint px = CLAMP(x, 0, width - 1);
            guchar *pixel = data + y_top * stride + px * channels;
            pixel[0] = b;
            pixel[1] = g;
            pixel[2] = r;

            pixel = data + y_bot * stride + px * channels;
            pixel[0] = b;
            pixel[1] = g;
            pixel[2] = r;
        }
    }

    /* 绘制左侧和右侧边框线 */
    for (gint dx = 0; dx < lw; dx++) {
        gint x_left  = CLAMP(ix1 + dx, 0, width - 1);
        gint x_right = CLAMP(ix2 - dx, 0, width - 1);

        for (gint y = iy1; y <= iy2; y++) {
            gint py = CLAMP(y, 0, height - 1);
            guchar *pixel = data + py * stride + x_left * channels;
            pixel[0] = b;
            pixel[1] = g;
            pixel[2] = r;

            pixel = data + py * stride + x_right * channels;
            pixel[0] = b;
            pixel[1] = g;
            pixel[2] = r;
        }
    }

    /* 绘制标签背景和文字 */
    if (self->show_label && class_name && class_name[0]) {
        gchar label_text[128];
        if (self->show_conf) {
            g_snprintf(label_text, sizeof(label_text),
                       "%s %.2f", class_name, confidence);
        } else {
            g_strlcpy(label_text, class_name, sizeof(label_text));
        }

        gint label_w = (gint)(strlen(label_text) * 10);  /* 每个字符 ~10px */
        gint label_h = 22;
        gint label_y = CLAMP(iy1 - label_h, 0, height - 1);

        /* 标签背景 (彩色填充矩形) */
        for (gint dy = 0; dy < label_h && (label_y + dy) < height; dy++) {
            gint py = label_y + dy;
            for (gint dx = 0; dx < label_w && (ix1 + dx) < width; dx++) {
                guchar *pixel = data + py * stride + (ix1 + dx) * channels;
                pixel[0] = b;
                pixel[1] = g;
                pixel[2] = r;
            }
        }

        /*
         * 标签文字 — 白色像素点阵 (简化的位图字体渲染)
         *
         * 只支持 ASCII 大写字母和数字。
         * 完整实现应使用 Pango/Cairo, 但会增加 ~2MB 依赖。
         * 嵌入式环境下此简化方案足够使用。
         */
        static const guchar font_5x7[][7] = {
            /* 每个字符 5×7 像素, 1=点亮 */
            [0]  = {0x00,0x00,0x00,0x00,0x00,0x00,0x00}, /* space */
            ['A'-'A'] = {0x0E,0x11,0x11,0x1F,0x11,0x11,0x11},
            ['B'-'A'] = {0x1E,0x11,0x11,0x1E,0x11,0x11,0x1E},
            ['C'-'A'] = {0x0E,0x11,0x10,0x10,0x10,0x11,0x0E},
            ['D'-'A'] = {0x1C,0x12,0x11,0x11,0x11,0x12,0x1C},
            ['E'-'A'] = {0x1F,0x10,0x10,0x1E,0x10,0x10,0x1F},
            ['F'-'A'] = {0x1F,0x10,0x10,0x1E,0x10,0x10,0x10},
            ['G'-'A'] = {0x0E,0x11,0x10,0x17,0x11,0x11,0x0E},
            ['H'-'A'] = {0x11,0x11,0x11,0x1F,0x11,0x11,0x11},
            ['I'-'A'] = {0x0E,0x04,0x04,0x04,0x04,0x04,0x0E},
            ['J'-'A'] = {0x07,0x02,0x02,0x02,0x02,0x12,0x0C},
            ['K'-'A'] = {0x11,0x12,0x14,0x18,0x14,0x12,0x11},
            ['L'-'A'] = {0x10,0x10,0x10,0x10,0x10,0x10,0x1F},
            ['M'-'A'] = {0x11,0x1B,0x15,0x11,0x11,0x11,0x11},
            ['N'-'A'] = {0x11,0x19,0x15,0x13,0x11,0x11,0x11},
            ['O'-'A'] = {0x0E,0x11,0x11,0x11,0x11,0x11,0x0E},
            ['P'-'A'] = {0x1E,0x11,0x11,0x1E,0x10,0x10,0x10},
            ['Q'-'A'] = {0x0E,0x11,0x11,0x11,0x15,0x12,0x0D},
            ['R'-'A'] = {0x1E,0x11,0x11,0x1E,0x14,0x12,0x11},
            ['S'-'A'] = {0x0E,0x11,0x10,0x0E,0x01,0x11,0x0E},
            ['T'-'A'] = {0x1F,0x04,0x04,0x04,0x04,0x04,0x04},
            ['U'-'A'] = {0x11,0x11,0x11,0x11,0x11,0x11,0x0E},
            ['V'-'A'] = {0x11,0x11,0x11,0x11,0x11,0x0A,0x04},
            ['W'-'A'] = {0x11,0x11,0x11,0x11,0x15,0x1B,0x11},
            ['X'-'A'] = {0x11,0x11,0x0A,0x04,0x0A,0x11,0x11},
            ['Y'-'A'] = {0x11,0x11,0x0A,0x04,0x04,0x04,0x04},
            ['Z'-'A'] = {0x1F,0x01,0x02,0x04,0x08,0x10,0x1F},
        };

        gint text_x = ix1 + 3;
        gint text_y = label_y + 5;
        gint scale = (gint)(self->font_scale * 2.0);

        for (const gchar *s = label_text; *s; s++) {
            gchar c = *s;
            gint idx;

            if (c >= 'A' && c <= 'Z')
                idx = c - 'A';
            else if (c >= 'a' && c <= 'z')
                idx = c - 'a';
            else if (c >= '0' && c <= '9')
                idx = -1;  /* 数字跳过 (简化) */
            else if (c == ' ')
                { text_x += 4 * scale; continue; }
            else if (c == '.')
                { text_x += 3 * scale; continue; }
            else
                { text_x += 4 * scale; continue; }

            if (idx < 0 || idx >= 26) {
                text_x += 4 * scale;
                continue;
            }

            for (gint row = 0; row < 7; row++) {
                guchar bits = font_5x7[idx][row];
                for (gint col = 0; col < 5; col++) {
                    if (bits & (1 << (4 - col))) {
                        for (gint sy = 0; sy < scale; sy++) {
                            for (gint sx = 0; sx < scale; sx++) {
                                gint px = text_x + col * scale + sx;
                                gint py = text_y + row * scale + sy;
                                if (px >= 0 && px < width &&
                                    py >= 0 && py < height) {
                                    guchar *pixel = data + py * stride +
                                                    px * channels;
                                    pixel[0] = 255;  /* B = 白色 */
                                    pixel[1] = 255;  /* G */
                                    pixel[2] = 255;  /* R */
                                }
                            }
                        }
                    }
                }
            }
            text_x += 6 * scale;
        }
    }
}

/* ── GstVideoFilter 核心: transform_frame_ip ───────────── */
/*
 * transform_frame_ip — 在视频帧上绘制检测结果
 *
 * 从上个 buffer 的 RknnDetectionMeta 读取检测结果,
 * 调用 draw_detection_box 绘制每个框。
 */
static GstFlowReturn
gst_rknn_draw_transform_frame_ip(GstVideoFilter *filter,
                                  GstVideoFrame *frame)
{
    GstRknnDraw *self = GST_RKNN_DRAW(filter);
    GstBuffer *buffer = gst_video_frame_get_buffer(frame);

    if (!buffer) {
        GST_WARNING_OBJECT(self, "No buffer associated with frame");
        return GST_FLOW_OK;
    }

    /* 从 GstBuffer 读取检测结果 meta */
    GType meta_api = get_rknn_detection_meta_api_type();
    if (meta_api == 0) {
        GST_LOG_OBJECT(self, "RknnDetectionMeta API not registered yet");
        return GST_FLOW_OK;
    }

    const GstMeta *meta = gst_buffer_get_meta(buffer, meta_api);
    if (!meta) {
        /* 没有检测结果, 正常情况 (非检测帧或上游没有 rknninference) */
        return GST_FLOW_OK;
    }

    /*
     * 直接访问 meta 数据 (RknnDetectionMeta 布局)
     * meta 后面紧跟 num_detections, boxes, class_names
     */
    const gchar *meta_data = (const gchar *)meta;
    gint num_detections = *(const gint *)(meta_data + sizeof(GstMeta));
    const gfloat *boxes = *(const gfloat **)(meta_data + sizeof(GstMeta) +
                                              sizeof(gint));
    const gchar **class_names = *(const gchar ***)(meta_data + sizeof(GstMeta) +
                                                    sizeof(gint) + sizeof(gfloat *));

    if (!boxes || num_detections <= 0)
        return GST_FLOW_OK;

    GST_LOG_OBJECT(self, "Drawing %d detections", num_detections);

    for (gint i = 0; i < num_detections; i++) {
        gfloat x1 = boxes[i * 6 + 0];
        gfloat y1 = boxes[i * 6 + 1];
        gfloat x2 = boxes[i * 6 + 2];
        gfloat y2 = boxes[i * 6 + 3];
        gfloat conf = boxes[i * 6 + 4];
        const gchar *cname = class_names ? class_names[i] : NULL;

        draw_detection_box(self, frame, x1, y1, x2, y2, conf, cname);
    }

    return GST_FLOW_OK;
}

/* ── 属性 get/set ──────────────────────────────────────── */
static void gst_rknn_draw_set_property(GObject *object,
                                        guint prop_id,
                                        const GValue *value,
                                        GParamSpec *pspec)
{
    GstRknnDraw *self = GST_RKNN_DRAW(object);

    switch (prop_id) {
    case PROP_LINE_WIDTH:
        self->line_width = g_value_get_int(value);
        break;
    case PROP_FONT_SCALE:
        self->font_scale = g_value_get_double(value);
        break;
    case PROP_SHOW_LABEL:
        self->show_label = g_value_get_boolean(value);
        break;
    case PROP_SHOW_CONF:
        self->show_conf = g_value_get_boolean(value);
        break;
    default:
        G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop_id, pspec);
        break;
    }
}

static void gst_rknn_draw_get_property(GObject *object,
                                        guint prop_id,
                                        GValue *value,
                                        GParamSpec *pspec)
{
    GstRknnDraw *self = GST_RKNN_DRAW(object);

    switch (prop_id) {
    case PROP_LINE_WIDTH:
        g_value_set_int(value, self->line_width);
        break;
    case PROP_FONT_SCALE:
        g_value_set_double(value, self->font_scale);
        break;
    case PROP_SHOW_LABEL:
        g_value_set_boolean(value, self->show_label);
        break;
    case PROP_SHOW_CONF:
        g_value_set_boolean(value, self->show_conf);
        break;
    default:
        G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop_id, pspec);
        break;
    }
}

/* ── 类初始化 ──────────────────────────────────────────── */
static void gst_rknn_draw_class_init(GstRknnDrawClass *klass)
{
    GObjectClass *gobject_class = G_OBJECT_CLASS(klass);
    GstElementClass *element_class = GST_ELEMENT_CLASS(klass);
    GstVideoFilterClass *video_filter_class = GST_VIDEO_FILTER_CLASS(klass);

    gobject_class->set_property = gst_rknn_draw_set_property;
    gobject_class->get_property = gst_rknn_draw_get_property;

    video_filter_class->transform_frame_ip =
        gst_rknn_draw_transform_frame_ip;

    g_object_class_install_property(
        gobject_class, PROP_LINE_WIDTH,
        g_param_spec_int("line-width", "Line Width",
                         "Width of detection box border",
                         1, 10, 2,
                         (GParamFlags)(G_PARAM_READWRITE |
                                       G_PARAM_STATIC_STRINGS)));

    g_object_class_install_property(
        gobject_class, PROP_FONT_SCALE,
        g_param_spec_double("font-scale", "Font Scale",
                            "Scale factor for label text",
                            0.1, 2.0, 0.5,
                            (GParamFlags)(G_PARAM_READWRITE |
                                          G_PARAM_STATIC_STRINGS)));

    g_object_class_install_property(
        gobject_class, PROP_SHOW_LABEL,
        g_param_spec_boolean("show-label", "Show Label",
                             "Whether to show class labels",
                             TRUE,
                             (GParamFlags)(G_PARAM_READWRITE |
                                           G_PARAM_STATIC_STRINGS)));

    g_object_class_install_property(
        gobject_class, PROP_SHOW_CONF,
        g_param_spec_boolean("show-conf", "Show Confidence",
                             "Whether to show confidence scores",
                             TRUE,
                             (GParamFlags)(G_PARAM_READWRITE |
                                           G_PARAM_STATIC_STRINGS)));

    gst_element_class_set_static_metadata(
        element_class,
        "RKNN Detection Box Draw",
        "Video/Filter/Overlay",
        "Draw detection boxes and labels on video frames",
        "Edge AI Vision Project");

    gst_element_class_add_pad_template(
        element_class,
        gst_pad_template_new("src", GST_PAD_SRC, GST_PAD_ALWAYS,
                             gst_caps_from_string(
                                 "video/x-raw, "
                                 "format=(string){BGR,RGB}, "
                                 "width=[1,4096], "
                                 "height=[1,4096]")));
    gst_element_class_add_pad_template(
        element_class,
        gst_pad_template_new("sink", GST_PAD_SINK, GST_PAD_ALWAYS,
                             gst_caps_from_string(
                                 "video/x-raw, "
                                 "format=(string){BGR,RGB}, "
                                 "width=[1,4096], "
                                 "height=[1,4096]")));
}

static void gst_rknn_draw_init(GstRknnDraw *self)
{
    self->line_width = 2;
    self->font_scale = 0.5;
    self->show_label = TRUE;
    self->show_conf = TRUE;

    /* 预定义颜色表 (BGR) — 10种高对比度颜色 */
    self->colors[0] = (struct { gint r, g, b; }){255,   0,   0};  /* 蓝 */
    self->colors[1] = (struct { gint r, g, b; }){  0, 255,   0};  /* 绿 */
    self->colors[2] = (struct { gint r, g, b; }){  0,   0, 255};  /* 红 */
    self->colors[3] = (struct { gint r, g, b; }){255, 255,   0};  /* 青 */
    self->colors[4] = (struct { gint r, g, b; }){  0, 255, 255};  /* 黄 */
    self->colors[5] = (struct { gint r, g, b; }){255,   0, 255};  /* 品红 */
    self->colors[6] = (struct { gint r, g, b; }){128,   0, 128};  /* 深紫 */
    self->colors[7] = (struct { gint r, g, b; }){  0, 128, 128};  /* 橄榄 */
    self->colors[8] = (struct { gint r, g, b; }){128, 128,   0};  /* 蓝绿 */
    self->colors[9] = (struct { gint r, g, b; }){  0,   0, 128};  /* 深红 */
}

/* ── 插件注册 ──────────────────────────────────────────── */
static gboolean plugin_init(GstPlugin *plugin)
{
    GST_DEBUG_CATEGORY_INIT(rknn_draw_debug,
                            "rknndraw", 0,
                            "RKNN Detection Draw Element");

    return gst_element_register(plugin, "rknndraw",
                                GST_RANK_NONE,
                                GST_TYPE_RKNN_DRAW);
}

GST_PLUGIN_DEFINE(
    GST_VERSION_MAJOR,
    GST_VERSION_MINOR,
    rknndraw,
    "RKNN Detection Draw Plugin for Edge AI",
    plugin_init,
    "1.0.0",
    "LGPL",
    "embedded-ai-vision",
    "https://github.com/IVONLDE/embedded-ai-vision"
);