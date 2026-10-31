from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .investment_forms import WatchForm, PortfolioForm, TradeForm, StrategyForm, HistoryPeriodForm
from .models import WatchItem, Notification, Portfolio, Strategy, Share, PriceHistory
from .services.investing import (starting_cursor, execute_trade, portfolio_summary,
                                 run_strategy, check_watch, strategy_summary)
from .services.graph import get_history_graph


def form_page(request, form, title):
    return render(request, 'dashboard/investments/form.html', {'form': form, 'title': title})


@login_required(login_url='user:auth')
def watchlist(request):
    form = WatchForm(request.POST or None, owner=request.user)
    if request.method == 'POST' and form.is_valid():
        watch = form.save(commit=False)
        watch.owner = request.user
        watch.last_history_id = starting_cursor(watch.share, watch.source)
        watch.save()
        return redirect('dashboard:watchlist')
    return render(request, 'dashboard/investments/watchlist.html', {
        'form': form, 'items': WatchItem.objects.filter(owner=request.user).select_related('share'),
    })


@login_required(login_url='user:auth')
@transaction.atomic
def watch_edit(request, pk):
    watch = get_object_or_404(WatchItem.objects.select_for_update(), pk=pk, owner=request.user)
    form = WatchForm(request.POST or None, instance=watch, owner=request.user)
    if request.method == 'POST' and form.is_valid():
        if {'condition', 'target'} & set(form.changed_data):
            watch.matched = False
            # Do not rewind the cursor: a new rule applies to the next quote.
        form.save()
        return redirect('dashboard:watchlist')
    return form_page(request, form, 'Изменить ценовое условие')


@login_required(login_url='user:auth')
@require_POST
def watch_delete(request, pk):
    get_object_or_404(WatchItem, pk=pk, owner=request.user).delete()
    return redirect('dashboard:watchlist')


@login_required(login_url='user:auth')
@require_POST
def watch_check(request, pk):
    watch = get_object_or_404(WatchItem, pk=pk, owner=request.user)
    count = check_watch(watch.pk)
    messages.success(request, f'Новых уведомлений: {count}.')
    return redirect('dashboard:notifications')


@login_required(login_url='user:auth')
def notifications(request):
    return render(request, 'dashboard/investments/notifications.html', {
        'notifications': Notification.objects.filter(owner=request.user).select_related('event'),
    })


@login_required(login_url='user:auth')
@require_POST
def notification_read(request, pk):
    notification = get_object_or_404(Notification, pk=pk, owner=request.user)
    notification.read = True
    notification.save(update_fields=['read'])
    return redirect('dashboard:notifications')


@login_required(login_url='user:auth')
def portfolios(request):
    form = PortfolioForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        portfolio = form.save(commit=False)
        portfolio.owner = request.user
        portfolio.save()
        return redirect('dashboard:portfolio', pk=portfolio.pk)
    return render(request, 'dashboard/investments/portfolios.html', {
        'portfolios': Portfolio.objects.filter(owner=request.user), 'form': form,
    })


@login_required(login_url='user:auth')
def portfolio(request, pk):
    portfolio = get_object_or_404(Portfolio, pk=pk, owner=request.user)
    form = TradeForm(request.POST or None, portfolio=portfolio)
    if request.method == 'POST' and form.is_valid():
        try:
            execute_trade(request.user, portfolio.pk, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect('dashboard:portfolio', pk=pk)
    rows, totals = portfolio_summary(portfolio)
    return render(request, 'dashboard/investments/portfolio.html', {
        'portfolio': portfolio, 'rows': rows, 'totals': totals, 'form': form,
        'trades': portfolio.trades.select_related('share'),
    })


@login_required(login_url='user:auth')
def strategies(request):
    form = StrategyForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        strategy = form.save(commit=False)
        strategy.owner = request.user
        strategy.currency = strategy.share.currency.lower()
        strategy.cash = strategy.initial_capital
        strategy.last_history_id = starting_cursor(strategy.share, strategy.source)
        strategy.save()
        return redirect('dashboard:strategy', pk=strategy.pk)
    return render(request, 'dashboard/investments/strategies.html', {
        'strategies': Strategy.objects.filter(owner=request.user).select_related('share'), 'form': form,
    })


@login_required(login_url='user:auth')
@transaction.atomic
def strategy(request, pk):
    strategy = get_object_or_404(Strategy.objects.select_for_update(), pk=pk, owner=request.user)
    form = StrategyForm(request.POST or None, instance=strategy)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('dashboard:strategy', pk=pk)
    return render(request, 'dashboard/investments/strategy.html', {
        'strategy': strategy, 'form': form, 'summary': strategy_summary(strategy),
        'executions': strategy.executions.select_related('event'),
    })


@login_required(login_url='user:auth')
@require_POST
def strategy_run(request, pk):
    strategy = get_object_or_404(Strategy, pk=pk, owner=request.user)
    count = run_strategy(strategy.pk)
    messages.success(request, f'Виртуальных сделок: {count}.')
    return redirect('dashboard:strategy', pk=pk)


def history(request, pk):
    share = get_object_or_404(Share, pk=pk)
    form = HistoryPeriodForm(request.GET if request.GET else {'source': settings.MARKET_DATA_PROVIDER})
    points, delta, percent = [], None, None
    if form.is_valid():
        query = PriceHistory.objects.filter(share=share, source=form.cleaned_data['source'], currency=share.currency.lower())
        for field, lookup in [('start', 'quoted_at__date__gte'), ('end', 'quoted_at__date__lte')]:
            day = form.cleaned_data[field]
            if day:
                query = query.filter(**{lookup: day})
        points = list(query.order_by('quoted_at', 'id'))
        if points:
            delta = points[-1].price - points[0].price
            percent = delta / points[0].price * 100
    return render(request, 'dashboard/investments/history.html', {
        'share': share, 'form': form, 'points': points, 'delta': delta, 'percent': percent,
        'plot_div': get_history_graph(points, share.currency),
    })
