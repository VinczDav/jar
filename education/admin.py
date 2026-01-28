from django.contrib import admin
from .models import (
    Course, Lesson, LessonAttachment, Exam, Question, Answer,
    ExamAttempt, AttemptAnswer
)


class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 1
    show_change_link = True


class ExamInline(admin.TabularInline):
    model = Exam
    extra = 0
    show_change_link = True


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('title', 'is_active', 'order')
    list_filter = ('is_active',)
    search_fields = ('title',)
    inlines = [LessonInline, ExamInline]


class LessonAttachmentInline(admin.TabularInline):
    model = LessonAttachment
    extra = 1


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('title', 'course', 'order')
    list_filter = ('course',)
    search_fields = ('title', 'content')
    inlines = [LessonAttachmentInline]


class AnswerInline(admin.TabularInline):
    model = Answer
    extra = 4


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('text', 'exam', 'order', 'points')
    list_filter = ('exam',)
    search_fields = ('text',)
    inlines = [AnswerInline]


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 1
    show_change_link = True


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ('title', 'course', 'passing_score', 'time_limit_minutes', 'is_active')
    list_filter = ('is_active', 'course')
    search_fields = ('title',)
    inlines = [QuestionInline]


class AttemptAnswerInline(admin.TabularInline):
    model = AttemptAnswer
    extra = 0
    readonly_fields = ('question', 'selected_answer', 'is_correct')
    can_delete = False


@admin.register(ExamAttempt)
class ExamAttemptAdmin(admin.ModelAdmin):
    list_display = ('referee', 'exam', 'started_at', 'status', 'score', 'percentage')
    list_filter = ('status', 'exam')
    search_fields = ('referee__user__first_name', 'referee__user__last_name')
    readonly_fields = ('started_at', 'completed_at', 'score', 'max_score', 'percentage')
    inlines = [AttemptAnswerInline]
