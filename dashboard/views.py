from django.contrib.auth.mixins import UserPassesTestMixin
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView, View

from .forms import ShareModelForm
from .models import Share
from .services.graph import get_graph


class IsUserAuthenticatedMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated

    def handle_no_permission(self):
        return redirect("dashboard:index")


class ShareListView(ListView):
    """Список акций"""

    model = Share
    template_name = "dashboard/list.html"
    paginate_by = 100
    ordering = ["name"]


class ShareDetailView(View):
    """Детальная информация об акции и график."""

    def get(self, request, pk):
        share = get_object_or_404(Share, pk=pk)
        return render(
            request,
            "dashboard/detail.html",
            {"plot_div": get_graph(share), "share": share},
        )


class ShareCreateView(IsUserAuthenticatedMixin, CreateView):
    """Добавление инструмента"""

    template_name = "dashboard/create.html"
    form_class = ShareModelForm
    success_url = reverse_lazy("dashboard:index")


class ShareUpdateView(IsUserAuthenticatedMixin, UpdateView):
    """Редактирование инструмента"""

    model = Share
    template_name = "dashboard/create.html"
    form_class = ShareModelForm
    success_url = reverse_lazy("dashboard:index")


class ShareDeleteView(IsUserAuthenticatedMixin, DeleteView):
    """Удаление инструмента"""

    model = Share
    template_name = "dashboard/delete.html"
    success_url = reverse_lazy("dashboard:index")

    def form_valid(self, form):
        try:
            return super().form_valid(form)
        except ProtectedError:
            return render(self.request, self.template_name, {
                'share': self.object,
                'error': 'Нельзя удалить акцию: она используется в истории цен или персональных данных.',
            }, status=409)
