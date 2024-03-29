from django.shortcuts import get_object_or_404, render, redirect
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from ipware import get_client_ip
import random
import string
import datetime
import json
from . import models
from . import forms


def index(request):
    return render(request, 'core/index.html')


@login_required
def app_index(request):
    apps = models.Application.objects.filter(user=request.user)
    context = {
        'apps': apps,
    }
    return render(request, 'core/apps/index.html', context)


@login_required
def app_create(request, app_id=None):
    app = None
    if app_id:
        app = get_object_or_404(models.Application, pk=app_id, user=request.user)
        if app.user != request.user:
            return HttpResponse("Unauthorized Access :(", status=403)
    if request.method == 'POST':
        form = forms.ApplicationForm(request.POST, instance=app)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.user = request.user
            obj.save()
            return redirect(obj)
    else:
        form = forms.ApplicationForm(instance=app)
    return render(request, 'core/apps/create.html', {'form': form})


@login_required
def app_details(request, app_id):
    app = get_object_or_404(models.Application, pk=app_id, user=request.user)
    if app.user != request.user:
        return HttpResponse("Unauthorized Access :(", status=403)
    keys = models.Key.objects.filter(app=app)
    return render(request, "core/apps/details.html", {'app': app, 'keys': keys})


@login_required
def app_delete(request, app_id):
    app = get_object_or_404(models.Application, pk=app_id, user=request.user)
    if app.user != request.user:
        return HttpResponse("Unauthorized Access :(", status=403)
    app.delete()
    return redirect('app_index')


@login_required
def key_index(request):
    keys = models.Key.objects.filter(user=request.user)
    context = {
        'keys': keys,
    }
    return render(request, 'core/keys/index.html', context)


@login_required
def key_create(request, app_id=None, key_id=None):
    app = None
    key = None
    if app_id:
        app = get_object_or_404(models.Application, pk=app_id, user=request.user)
        if app.user != request.user:
            return HttpResponse("Unauthorized Access :(", status=403)
    if key_id:
        key = get_object_or_404(models.Key, pk=key_id, user=request.user)
        if key.user != request.user:
            return HttpResponse("Unauthorized Access :(", status=403)
    if request.method == 'POST':
        form = forms.KeyForm(request.POST, instance=key, user=request.user)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.user = request.user
            obj.save()
            ip, routable = get_client_ip(request)
            if ip:
                ip += " (Routable)" if routable else " (Unroutable)"
            if key:
                models.AuditLog.objects.create(
                    app=obj.app, key=obj, user=request.user,
                    description=f"Key modified by {request.user.username} ({ip})",
                    event="KeyModify")
            else:
                models.AuditLog.objects.create(
                    app=obj.app, key=obj, user=request.user,
                    description=f"New key created by {request.user.username} ({ip})",
                    event="KeyCreate")
            return redirect(obj)
    else:
        if key:
            form = forms.KeyForm(instance=key, user=request.user)
        else:
            rand_token = ''.join(
                [random.choice(string.ascii_uppercase+string.digits) for _ in range(16)])
            initial_data = {'token': rand_token}
            if app:
                initial_data.update({'app': app})
            form = forms.KeyForm(initial=initial_data, user=request.user)
    return render(request, 'core/keys/create.html', {'form': form})


@login_required
def key_details(request, key_id):
    key = get_object_or_404(models.Key, pk=key_id, user=request.user)
    if key.user != request.user:
        return HttpResponse("Unauthorized Access :(", status=403)
    return render(request, "core/keys/details.html", {'key': key})


@login_required
def key_delete(request, key_id):
    key = get_object_or_404(models.Key, pk=key_id, user=request.user)
    if key.user != request.user:
        return HttpResponse("Unauthorized Access :(", status=403)
    key.delete()
    return redirect('key_index')


@login_required
def audit_log(request):
    logs = models.AuditLog.objects.filter(user=request.user).order_by('-created_at')
    return render(request, "core/logs.html", {'logs': logs})


@csrf_exempt
def api_check(request):
    if request.method != 'GET':
        return JsonResponse(
            {'result': 'failure', 'error': 'Only GET allowed'},
            status=405)
    try:
        token = request.GET['token']
        app_id = request.GET['app_id']
        device_name = request.GET.get('device_name')
        hwid = request.GET['hwid']
        try:
            app = models.Application.objects.get(id=app_id)
            key = models.Key.objects.get(
                token=token, app=app, hwid=hwid)
        except (models.Key.DoesNotExist, models.Application.DoesNotExist):
            return JsonResponse(
                {'result': 'failure', 'error': 'Invalid key'},
                status=404)
        if not key.active:
            return JsonResponse(
                {'result': 'failure', 'error': 'Key not active'},
                status=410)
        if device_name and device_name != key.device_name:
            key.device_name = device_name
        key.last_check = datetime.datetime.now()
        key.save()
        ip, routable = get_client_ip(request)
        if ip:
            ip += " (Routable)" if routable else " (Unroutable)"
        models.AuditLog.objects.create(
            app=app, key=key, user=key.user,
            description=f"Checked from IP: {ip}. Device Name: {key.device_name}",
            event="KeyCheck")
        return JsonResponse({'result': 'ok'}, status=200)
    except KeyError as e:
        return JsonResponse(
            {'result': 'failure', 'error': f'{e.args[0]} not given'},
            status=405)


@csrf_exempt
def api_activate(request):
    if request.method != 'POST':
        return JsonResponse(
            {'result': 'failure', 'error': 'Only POST allowed'},
            status=405)
    try:
        token = request.POST['token']
        app_id = request.POST['app_id']
        device_name = request.POST.get('device_name')
        hwid = request.POST['hwid']
        try:
            app = models.Application.objects.get(id=app_id)
            key = models.Key.objects.get(
                token=token, app=app)
        except (models.Key.DoesNotExist, models.Application.DoesNotExist):
            return JsonResponse(
                {'result': 'failure', 'error': 'Invalid token'},
                status=404)
        if not key.active:
            return JsonResponse(
                {'result': 'failure', 'error': 'Key not active'},
                status=410)
        if key.activations == 0 or key.activations < -1:
            return JsonResponse(
                {'result': 'failure', 'error': 'No further activations allowed'},
                status=410)
        if key.activations != -1:
            key.activations -= 1
        key.hwid = hwid
        key.device_name = device_name
        key.last_activation = datetime.datetime.now()
        key.save()
        ip, routable = get_client_ip(request)
        if ip:
            ip += " (Routable)" if routable else " (Unroutable)"
        models.AuditLog.objects.create(
            app=app, key=key, user=key.user,
            description=f"Activated from IP: {ip}. Device Name: {key.device_name}. Remaining Activations: {key.activations}",  # noqa
            event="KeyActivate")
        return JsonResponse(
            {'result': 'ok', 'remaining_activations': key.activations},
            status=200)
    except KeyError as e:
        return JsonResponse(
            {'result': 'failure', 'error': f'{e.args[0]} not given'},
            status=405)


@csrf_exempt
def api_bulk_key_create(request):
    if request.method != 'POST':
        return JsonResponse(
            {'result': 'failure', 'error': 'Only POST allowed'},
            status=405)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse(
            {'result': 'failure', 'error': 'Error in JSON.'},
            status=405)
    try:
        app_id = data['app_id']
        master_key = data['master_key']
        _keys = data['keys']
        try:
            app = models.Application.objects.get(id=app_id, master_key=master_key)
        except (models.Key.DoesNotExist, models.Application.DoesNotExist):
            return JsonResponse(
                {'result': 'failure', 'error': 'Invalid token'},
                status=404)
        keys = []
        logs = []
        ip, routable = get_client_ip(request)
        if ip:
            ip += " (Routable)" if routable else " (Unroutable)"
        for k in _keys:
            kwargs = {
                'user': app.user,
                'app': app,
                'token': k['token'],
            }
            if 'activations' in k:
                kwargs.update({'activations': k['activations']})
            if 'active' in k:
                kwargs.update({'active': k['active']})
            if 'description' in k:
                kwargs.update({'description': k['description']})
            keys.append(models.Key(**kwargs))
        models.Key.objects.bulk_create(keys)
        for key in keys:
            logs.append(models.AuditLog(
                app=app, key=key, user=app.user,
                description=f"New key created by {app.user.username} ({ip})",
                event="KeyCreate"))
        models.AuditLog.objects.bulk_create(logs)
        return JsonResponse(
            {'result': 'ok', 'created': len(keys)},
            status=200)
    except KeyError as e:
        return JsonResponse(
            {'result': 'failure', 'error': f'{e.args[0]} not given'},
            status=405)
