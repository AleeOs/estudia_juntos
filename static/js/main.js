document.addEventListener('DOMContentLoaded', () => {
    // Escuchar clics en los botones de cambio de estado
    document.querySelectorAll('.btn-toggle-status').forEach(button => {
        button.addEventListener('click', async (e) => {
            const userId = button.getAttribute('data-user-id');
            const badge = document.getElementById(`user-badge-${userId}`);

            // Deshabilitar botón temporalmente durante la petición
            button.disabled = true;

            try {
                const response = await fetch(`/toggle_estado_usuario/${userId}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });

                const data = await response.json();

                if (data.success) {
                    if (data.nuevo_estado) {
                        // Usuario activado
                        badge.className = 'badge bg-success';
                        badge.textContent = 'Activo';

                        button.className = 'btn btn-sm btn-toggle-status btn-outline-danger';
                        button.textContent = 'Inactivar';
                    } else {
                        // Usuario inactivado
                        badge.className = 'badge bg-danger';
                        badge.textContent = 'Inactivo';

                        button.className = 'btn btn-sm btn-toggle-status btn-outline-success';
                        button.textContent = 'Activar';
                    }
                } else {
                    alert(data.message || 'Hubo un error al cambiar el estado.');
                }
            } catch (error) {
                console.error('Error:', error);
                alert('Ocurrió un error en la comunicación con el servidor.');
            } finally {
                button.disabled = false;
            }
        });
    });
});